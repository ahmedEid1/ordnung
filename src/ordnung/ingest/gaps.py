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
allows:

* **the period** is the one of every period the notices state (and the sentence after each, when that one
  goes on about it) that ends first, counted from the letter's date; it is dated only when that is at least a
  week and at most a month (every domestic remedy period is: § 70/§ 74 VwGO, § 355 AO, § 47 FGO, § 84/§ 87
  SGG, § 67 OWiG, § 410 StPO, § 692 ZPO), and when no notice holds a period that can't be read or dated
  (Werktage, years) or that counts back from an event ("zwei Wochen vor …") — otherwise the to-do is filed
  without a date, to be found in the letter;
* **the start** is the earliest date the letter gives for itself (:func:`letter_date`): dates its words name
  as its own (a "Datum" label, a place and date in its header, the reference line, "mit diesem Bescheid vom
  …", the decision its notice names, the reading's date) set it — none when those are more than two weeks
  apart, and none from one date alone long before the letter arrived; other dates (another "…datum", a date
  alone, a continuation page's) only lower it, never set it. Deemed delivery is added only when every notice
  counts from notification, by post (or the day after a portal download), never on formal service.
  Recomputed later, an earlier letter date or arrival still moves it earlier (:func:`start_variants`), never
  later;
* without a notice it is an undated "Read this letter yourself".

A reading that does date the objection, but later than the period the letter's own notice gives (a planted
"extended" period, a start moved later), gets that period beside its own date (:func:`notice_rival`, counted
from the date the first page names as its own): the earlier is kept and the to-do is "Please check"
(:func:`~ordnung.ingest.plan.compute_item`).

Nothing here calls a model; the reading itself (its sender, date and remedy) stays as the model gave it.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Literal, NamedTuple

from ordnung.ingest.conflicts import Rival, header, letter_statements, sentences
from ordnung.ingest.normalize import fold_punctuation, join_hyphenated
from ordnung.ingest.text import PageText
from ordnung.ingest.verify import (
    DATE_NOT_IN_QUOTE,
    PERIOD_NOT_IN_QUOTE,
    READING_INCOMPLETE,
    PageInput,
    date_spans,
    parse_periods,
)
from ordnung.models import (
    DateSpec,
    DocumentExtraction,
    ExtractedChange,
    ExtractedContract,
    ExtractedItem,
    Grounding,
    PaymentDetails,
)
from ordnung.rules import RuleContext
from ordnung.rules.delivery import shows_administrative_act
from ordnung.rules.routing import letter_kind, special_rule

__all__ = [
    "CHECK_SLOT",
    "LAW_DATED_KINDS",
    "NOTICE_REACH",
    "Check",
    "CheckKind",
    "Gap",
    "RemedyNotice",
    "check_item",
    "check_reasons",
    "dates_the_objection",
    "gap_warning",
    "letter_date",
    "notice_rival",
    "reading_gap",
    "remedy_notices",
    "start_variants",
]

#: Slot of the to-do code files for an incomplete reading (one per letter).
CHECK_SLOT = "check:reading"
#: The kinds of letter whose deadlines the law files itself (``routing.derived_deadlines``, through
#: ``plan.law_deadlines``): a court payment order read as "pay" still gets "pay or object".
LAW_DATED_KINDS = frozenset(
    {"court_payment_order", "enforcement_order", "dismissal", "landlord_notice", "rent_increase"}
)
#: The shortest deadline the law gives each of those kinds, in days (two weeks for a court's payment or
#: enforcement order, three for a dismissal, two months for a rent increase; a landlord's notice counts back
#: from the tenancy's end, so no notice period vouches for it).
_LAW_DAYS: dict[str, int] = {
    "court_payment_order": 14,
    "enforcement_order": 14,
    "dismissal": 21,
    "rent_increase": 59,
}
#: What the letter's own words must say for a reading's law-dated kind to count without such a period.
_LAW_WORDS: dict[str, tuple[re.Pattern[str], ...]] = {
    "court_payment_order": (re.compile(r"mahnbescheid|mahngericht", re.I),),
    "enforcement_order": (re.compile(r"vollstreckungsbescheid", re.I),),
    "dismissal": (re.compile(r"kündig", re.I), re.compile(r"arbeitsverh(?:ä|ae)ltnis", re.I)),
    "landlord_notice": (re.compile(r"kündig", re.I), re.compile(r"miet|wohnung", re.I)),
    "rent_increase": (re.compile(r"mieterh(?:ö|oe)hung|§\s*558", re.I),),
}

Gap = Literal["empty", "remedy_left_out"]
#: The to-do :func:`check_item` files: a dated objection deadline, one Ordnung couldn't date, or an undated
#: "Read this letter yourself".
CheckKind = Literal["dated", "undated", "read_yourself"]
Unit = Literal["days", "weeks", "months"]


class Check(NamedTuple):
    """What :func:`check_item` found: why the reading is incomplete, the to-do, which kind it is, and the
    remedy the notice names (``""`` for the placeholder)."""

    gap: Gap
    item: ExtractedItem
    kind: CheckKind
    remedy: str


_REMEDY = re.compile(r"widerspr\w*|einspr\w*|\bklage\w*|\bobjection\w*|\bobject\b|\bappeal\w*", re.IGNORECASE)
_GERMAN_REMEDY = re.compile(r"widerspr\w*|einspr\w*|\bklage\w*", re.IGNORECASE)
#: The decision a remedy was already lodged against names no remedy: "in Gestalt dieses Widerspruchsbescheids
#: kann … Klage …", "ohne Widerspruchsverfahren … Klage", "über Ihren Einspruch … Klage" are court actions.
_DECISION_ON_REMEDY = re.compile(
    r"\w*(?:widerspruchsbescheid|einspruchsentscheidung|widerspruchsverfahren|vorverfahren)\w*"
    r"|\büber\s+(?:\w+\s+){0,2}(?:widerspruch|einspruch)\w*",
    re.IGNORECASE,
)
#: A sentence after the notice that speaks of money is no part of it.
_PAYMENT = re.compile(r"zahl|überweis|fällig|betrag|\bpay\w*|\bdue\b", re.IGNORECASE)
_MONTH_PERIOD = re.compile(r"\bmonatsfrist\b", re.IGNORECASE)
#: A notice that is no live remedy against this letter: a later decision's, one already lodged or that should
#: have been ("ist … eingegangen", never "wenn er … eingegangen ist"), a direct debit's (Lastschrift next to
#: the remedy), a hint at a court action for inaction, or one on a decision not yet made ("gegen einen
#: Bescheid", "sollten wir …") — only whether the check fires: never its date.
_NOT_LIVE = re.compile(
    r"(?:späteren|künftigen)\s+\w*bescheid|\bhätten\b|\beingelegt\s+haben\b|"
    r"\b(?:ist|sind|wurde|wurden)\s+(?:(?!wenn\b|sofern\b|falls\b|soweit\b)\S+\s+){0,4}?eingegangen\b|"
    r"\bbegründen\s+Sie\s+(?:Ihren|Ihre|die|den)\s+(?:widerspruch|einspruch|klage)|"
    r"lastschrift\W+(?:\w+\W+){0,2}widersprech|(?:widerspr|einspr)\w*\W+(?:\w+\W+){0,2}lastschrift|"
    r"\bkein(?:en)?\s+(?:neuer\s+)?(?:bescheid|verwaltungsakt)\b|"
    r"untätigkeitsklage|\bgegen\s+(?:einen|eine|ein)\s+\w*(?:bescheid|entscheidung)|\bsollten\s+wir\b|"
    # a remedy taken as lodged ("Wenn Sie Widerspruch einlegen, reichen Sie … nach"): its period is another's
    r"\b(?:wenn|falls|sofern|soweit)\s+sie\s+(?:\w+\s+){0,3}(?:widerspruch|einspruch|klage)\w*\s+(?:\w+\s+){0,2}"
    r"(?:einlegen|erheben|einreichen|eingelegt\s+haben|erhoben\s+haben),",
    re.IGNORECASE,
)
#: A word of how a remedy is sent ("per E-Mail", "am Telefon"): ruling that form out leaves the remedy live.
_NOT_FORM = r"(?!(?:per|durch|mittels|am|telefon\w*|e-?mail\w*|fax\w*|mündlich\w*|elektronisch\w*)\b)"
#: A remedy the letter rules out: "Ein Widerspruch ist (gegen dieses Schreiben) nicht möglich", "Gegen dieses
#: Schreiben ist ein Widerspruch nicht zulässig", "Sie können gegen dieses Schreiben keinen Widerspruch
#: einlegen" — never a way of sending it ruled out (:data:`_NOT_FORM`).
_NEGATED = re.compile(
    rf"(?:widerspruch|einspruch)\w*\s+(?:{_NOT_FORM}\w+\s+){{0,3}}(?:ist|sind)\s+(?:{_NOT_FORM}\w+\s+){{0,4}}"
    r"nicht\s+(?:möglich|zulässig|statthaft)|"
    rf"\b(?:ist|sind)\s+(?:ein|eine|der|die)\s+(?:widerspruch|einspruch)\w*\s+(?:{_NOT_FORM}\w+\s+){{0,2}}"
    r"nicht\s+(?:möglich|zulässig|statthaft)|"
    r"\b(?:können|kann)\s+(?:\w+\s+){0,4}keinen?\s+(?:widerspruch|einspruch)\w*\s+(?:einlegen|erheben)",
    re.IGNORECASE,
)
#: The person's own objection being handled ("Über Ihren Widerspruch entscheiden wir …", "Die Bearbeitung Ihres
#: Widerspruchs dauert …"): no notice — but only when the sentence names no start and no way of lodging one.
_HANDLED = re.compile(
    r"\b(?:über|bearbeitung|ihr(?:e[nmrs]?)?)\s+(?:\w+\s+){0,2}(?:widerspruch|einspruch)", re.IGNORECASE
)
_LODGED = re.compile(
    r"erheb|erhob|einleg|eingeleg|einzuleg|einreich|eingereich|einzureich|widersprech|widersproch|frist|"
    r"einlegung|erhebung|eingegangen\s+sein|eingehen",
    re.IGNORECASE,
)
#: A line that goes on with the sentence of the line before ("vom 01.10.2026 können Sie …", "eines Monats …").
_CONTINUED = re.compile(r"\s*(?:vom\b|\d|[a-zäöüß])")
#: Where a clause of the notice starts ("…, vielmehr kann … Klage …").
_CLAUSE = re.compile(
    r"[,;]\s+(?=(?:vielmehr|jedoch|aber|sie|gegen|stattdessen|ein|der|die)\b)", re.IGNORECASE
)
#: The sentence after a notice without a period of its own speaks of the remedy's period when it says so.
_LIVE_FOLD = re.compile(
    r"frist|bekanntgabe|bekannt\s*gegeben|zustell|zugang|zugegangen|beginnt|einzulegen|zu\s+erheben|einzureichen",
    re.IGNORECASE,
)
_CONTRADICTORY = re.compile(r"widersprüchlich\w*", re.IGNORECASE)
_UNIT_WORD = r"(?:tag|tage|tagen|tages|woche|wochen|monat|monate|monaten|monats|jahr|jahre|jahren|jahres|days?|weeks?|months?|years?)"
#: A period counted back from an event: its unit followed by "vor", "bevor", "vorher", "zuvor", "before",
#: "prior to" or "in advance" — not with a start between ("nach Zustellung vor dem Sozialgericht", "of service
#: before the authority"), nor "vor dem …gericht" / "before the … court" (where the remedy is lodged).
_BACKWARD = re.compile(
    rf"\b{_UNIT_WORD}\b[\s,]*"
    r"(?:(?!klage|widerspr|einspr|nach\b|ab\b|seit\b|of\b|after\b|from\b|following\b)[^\W\d_]+[\s,]+){0,2}?"
    r"(?:vor(?!\s+(?:dem|der|einem|einer)\s+\w*(?:gericht|behörde)|\s+ort\b)|bevor|vorher|zuvor"
    r"|before(?!\s+(?:the\s+|an?\s+)?(?:\w+\s+){0,2}(?:court|authority|tribunal))|prior\s+to|in\s+advance)\b",
    re.IGNORECASE,
)
#: A start that runs forward from this letter.
_FORWARD = re.compile(
    r"\b(?:nach|ab|seit|mit)\s+(?:\w+\s+){0,3}?(?:bekanntgabe|zustellung|zugang|erhalt|eingang|empfang)\b"
    r"|bekannt\s*gegeben|zugestellt|zugegangen"
    r"|\b(?:after|of|from|following)\s+(?:the\s+)?(?:notification|service|receipt|delivery)\b|\bnotified\b",
    re.IGNORECASE,
)
#: A period written in a form the parser can't count ("einen Kalendermonat", "14-tägig", "Zweiwochenfrist").
_ODD_PERIOD = re.compile(
    r"kalender(?:woche|monat|jahr)\w*|(?:\d+\s*-?\s*|\b\w+)(?:tägig|wöchig|monatig)\w*|\b\w*(?:wochen|monats|tages)frist\b",
    re.IGNORECASE,
)
#: A number and a unit within a few words: where a period is written (to bound the quote around it).
_PERIOD_WORDS = re.compile(
    rf"(?:\b\d+|\b(?:ein|eine|einen|eines|einem|einer|one|a|an|zwei|two|drei|three|vier|four|fünf|five|sechs|six|sieben|seven|acht|eight"
    rf"|neun|nine|zehn|ten|elf|eleven|zwölf|twelve|vierzehn|fourteen|zwanzig|twenty|dreißig|dreissig|thirty))\W+"
    rf"(?:[^\W\d_]+\W+){{0,2}}?\w*{_UNIT_WORD}\b|monatsfrist",
    re.IGNORECASE,
)
#: Counted from notification (Bekanntgabe): deemed delivery after the letter's date.
_NOTIFIED = re.compile(r"bekanntgabe|bekannt\s*gegeben|\bnotif(?:ication|ied)\b", re.IGNORECASE)
#: Counted from formal service or arrival: from the letter's date itself, the earliest it can have arrived.
_ARRIVAL = re.compile(
    r"zustell\w*|zugestellt|\bzugang\b|zugegangen|\berhalt\b|\breceipt\b|\bservice\b|\bserved\b",
    re.IGNORECASE,
)
#: Formal service (Postzustellungsurkunde and the like): notified on the day it is served, no delivery days.
_FORMAL_SERVICE = re.compile(
    r"zustellungsurkunde|empfangsbekenntnis|rückschein|persönlich\s+(?:ausgehändigt|übergeben)|\bpzu\b"
    r"|förmlich\w*\s+zu(?:stellung|gestellt)|(?-i:\bmit\s+ZU\b)",
    re.IGNORECASE,
)
#: Provided for download (a portal or electronic mailbox): the day after the earliest download.
_PORTAL = re.compile(
    r"zum\s+(?:abruf|download)\s+bereit\w*|bürgerportal|nutzerkonto|elektronisch\w*\s+(?:post)?fach|online-?postfach",
    re.IGNORECASE,
)
#: "Musterstadt, 06.11.2026" / "Musterstadt, den 06.11.2026": a place and the letter's date.
_PLACE_DATE = re.compile(r"^[A-ZÄÖÜ][\w .\-/()]{1,40},\s*(?:den\s+)?$")
#: "Datum 06.11.2026", "Bescheiddatum: …", "Erstellt am …": a label of the letter's own date.
_DATE_LABEL = re.compile(
    r"(?:^|[\s·|])(?:\w*datum|datum\s+(?:des|der)\s+\w+|date|(?:erstellt|ausgestellt)\s+am)\s*:?\s*$",
    re.IGNORECASE,
)
#: A line that labels the date under or after it as another one ("Antrag vom", "geboren am").
_ANOTHER = re.compile(r"\b(?:vom|seit|bis|ab|am|zum|antrag\w*|geboren|geburtsdatum)\s*:?\s*$", re.IGNORECASE)
#: Words of a date that is not the letter's: a due day, a validity, an appointment, a weekday before it.
_OTHER_DATE = re.compile(
    r"\b(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag|monday|tuesday|wednesday"
    r"|thursday|friday|saturday|sunday|valid\w*|until|due|bis|ab|am|zum|vom|seit)\b|fällig|zahlung|zahlbar|"
    r"gültig|termin|anhörung|beginn|geburt|ablauf|liefer|leistung|zeitraum|frist|eingang|antrag|\bende\b",
    re.IGNORECASE,
)
_CREATED_ON = re.compile(r"(?:erstellt|ausgestellt)\s+am", re.IGNORECASE)
#: A label that names the letter's own date; any other "…datum" may be another's ("Einzugsdatum").
_OWN_LABEL = re.compile(
    r"(?:^|[\s·|])(?:(?:bescheid|brief|ausstellungs|ausfertigungs|erstellungs|druck|bearbeitungs)?datum|date"
    r"|datum\s+(?:des|der)\s+(?:bescheid\w*|schreiben\w*|brief\w*)|(?:erstellt|ausgestellt)\s+am)\s*:?\s*$",
    re.IGNORECASE,
)
#: The DIN 5008 reference line's labels, ending in "Datum" ("Ihr Zeichen  Unser Zeichen  Datum").
_REFERENCE_LABELS = re.compile(r"(?:^|\s)datum\s*:?$", re.IGNORECASE)
_DECISION = (
    r"(?:bescheid\w*|festsetzung\w*|entscheidung\w*|verfügung\w*|beschluss\w*|urteil\w*|verwaltungsakt\w*)"
)
#: A word that dates something other than the decision when it stands right before "vom".
_NOT_ISSUER = r"(?:antrag\w*|schreiben\w*|nachricht\w*|anhörung\w*|mitteilung\w*|widerspruch\w*|einspruch\w*)"
#: "Bescheid (der Stadt Beispielhausen, über die Abfallgebühr, 2026) vom 01.10.2026" in a notice: the decision it
#: is about was issued then — a decision's noun and words of its issuer or subject, within the clause (never past
#: a comma: "Bescheid, mit dem Ihr Antrag vom …"), never "Antrag vom", "(Ihr) Schreiben vom", "Anhörung vom".
_ISSUED = re.compile(
    rf"{_DECISION}(?:\s+(?!{_NOT_ISSUER}\s+vom\b)[^\s,;:]+){{0,8}}?\s+vom\s*$", re.IGNORECASE
)
#: "Schreiben vom 01.10.2026" in a notice (never "Ihr Schreiben"): perhaps the decision's date, perhaps
#: another's — a weak date of the letter's (:func:`letter_date`).
_LETTER_ISSUED = re.compile(r"(?<!ihr )(?<!ihrem )\bschreiben\w*\s+vom\s*$", re.IGNORECASE)
#: The same, from "gegen" at the start of the notice's sentence (its first line may be cut by a wrap).
_AGAINST_ISSUED = re.compile(
    rf"\bgegen\s+(?:\w+\s+){{0,2}}\w*{_DECISION}(?:\s+(?!{_NOT_ISSUER}\s+vom\b)[^\s,;:]+){{0,8}}?\s+vom\s*$",
    re.IGNORECASE,
)
#: The decision this letter reshapes ("Bescheid vom … in Gestalt dieses Widerspruchsbescheids"): its period runs
#: from this letter.
_RESHAPED = re.compile(r"\s*in\s+(?:der\s+)?(?:gestalt|fassung|form)\s+(?:dieses|des|der)\b", re.IGNORECASE)

_UNITS: dict[str, Unit] = {"days": "days", "weeks": "weeks", "months": "months"}
_DAYS: dict[str, int] = {"days": 1, "weeks": 7, "months": 31}
#: The periods dated: at most a month (every domestic remedy period), at least a week (none is shorter; an
#: attacker's "binnen eines Tages" gets no date to push onto Today).
_DATABLE_MAX: dict[str, int] = {"days": 31, "weeks": 4, "months": 1}
_DATABLE_MIN_DAYS = 7
#: The letter's dates for itself more than this far apart: one of them is another's, so no start is taken.
LETTER_DATE_SPAN = 14
#: A start resting on one date alone this many days before the letter arrived (or was read) is none: a stray
#: date ("Hauptveranlagung auf den 01.01.2025") would give an overdue to-do.
STALE_DAYS = 60
#: How many days deemed delivery can take (the 4th day, moved past a weekend and Easter, or a little more).
_DELIVERY_REACH = 35
#: The longest quote a code-made to-do keeps (the notice's words around its remedy and its period).
QUOTE_CAP = 600
#: How many days later than the letter's own notice gives a reading's objection date may be before that
#: notice's date is set beside it (:func:`notice_rival`), for a start or delivery days read differently:
#: measured on every recorded reading, 0 to 7 days (the days until a letter counts as delivered, a Land's
#: holiday, a weekend). A longer period than the notice's is set beside it whatever the gap
#: (:func:`~ordnung.ingest.plan.compute_item`).
NOTICE_REACH = 7
_REMEDIES = (("widerspr", "widerspruch"), ("einspr", "einspruch"), ("klage", "klage"))
_TITLES = {
    "widerspruch": "Deadline to object (Widerspruch)",
    "einspruch": "Deadline to object (Einspruch)",
    "klage": "Deadline for a court action (Klage)",
}

DEADLINE_ACTION = (
    "If you disagree with this decision, send your objection so that it arrives by the deadline. Ordnung took "
    "the deadline from the letter's own instructions on how to object — check it against the letter first."
)
DEADLINE_CONSEQUENCE = "After the deadline the decision can usually no longer be challenged."
KLAGE_ACTION = (
    "If you disagree with this decision, a court action (Klage) must reach the court the letter names by the "
    "deadline — a letter to the authority does not stop this deadline. Get advice (e.g. a Verbraucherzentrale) "
    "well before it. Ordnung took the deadline from the letter's own instructions — check it against the letter "
    "first."
)
KLAGE_CONSEQUENCE = "After the deadline the decision can usually no longer be challenged in court."
#: Added to the action when the letter carries text addressed to an AI: where to send it.
KNOWN_ADDRESS = (
    "Send it only to an address you already know for this authority or court — not to a link, e-mail address or "
    "phone number in this letter."
)
PLACEHOLDER_ACTION = (
    "Claude's reading of this letter came back almost blank. Read the letter yourself; if it asks you to do "
    "something by a date, give this to-do that date, and mark it done only once you have done what the letter asks."
)
_PREFIX: dict[Gap, str] = {
    "empty": "Claude's reading of this letter came back almost blank: the sender, the letter's date and its "
    "to-dos were all left out.",
    "remedy_left_out": "This letter explains how to object, but Claude's reading left out the deadline to object.",
}
_COURT_PREFIX = (
    "This letter explains how to challenge it in court, but Claude's reading left out the deadline for the court "
    "action."
)
_SUFFIX: dict[CheckKind, str] = {
    "dated": "Ordnung added the deadline from the letter's own instructions on how to object "
    "(Rechtsbehelfsbelehrung) — please check it against the letter before you rely on it.",
    "undated": "Ordnung found the letter's instructions on how to object but couldn't work out the deadline from "
    "them — please find it in the letter and enter it with “Set a date”.",
    "read_yourself": "Please read the letter yourself; if it asks you to do something by a date, give the to-do "
    "“Read this letter yourself” that date.",
}


@dataclass(frozen=True)
class RemedyNotice:
    """A sentence of the letter that names a remedy and a period — with the sentence after it when that one
    neither names a remedy nor speaks of money (a notice's period is often there).

    ``quote``: its words around the remedy and the period, at most :data:`QUOTE_CAP` characters (``text``: all
    of them); ``periods``: every period of days, weeks or months it states, as ``(amount, unit)``;
    ``notified``: counted from notification (deemed delivery), not from service or arrival; ``remedy``:
    ``widerspruch``, ``einspruch``, ``klage`` or ``objection``; ``live``: a remedy against this letter, not
    a later decision's, one already lodged, a direct debit's, one ruled out or one counted back from an event
    (whether the check fires — a notice that isn't live still counts for the date);
    ``datable``: every period it states can be read and runs forward, and its words fit the quote;
    ``issued``: the dates of the decisions it names ("Bescheid vom …"); ``grounding``: how its page was read
    (a text layer or a photo's transcript); ``stated``: the periods its own sentence states (the sentence
    after it only when it has none of its own) — never an instruction folded in after it; ``mentioned``: the
    dates of letters it names ("Schreiben vom …"), weak dates of the letter's."""

    quote: str
    text: str
    periods: tuple[tuple[int, Unit], ...]
    notified: bool
    remedy: str
    live: bool
    datable: bool
    issued: tuple[date, ...]
    grounding: Grounding = "verified"
    stated: tuple[tuple[int, Unit], ...] = ()
    mentioned: tuple[date, ...] = ()

    @property
    def days(self) -> int:
        """Its shortest period's length for ranking, a month as 31 days (a very long one without a period)."""
        return min((amount * _DAYS[unit] for amount, unit in self.periods), default=10**6)


def _visible(page: PageInput) -> str:
    """The page's visible text (a photo's transcript), never its hidden text."""
    return page[1] if isinstance(page, tuple) else page.text


def _grounding(page: PageInput) -> Grounding:
    """How the page's text was read: its text layer (``verified``) or an AI transcript (``model_read``)."""
    if isinstance(page, tuple):
        source = page[3]
    elif isinstance(page, PageText):
        source = page.source
    else:
        source = page.text_source
    return "verified" if source == "text" else "model_read"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _matchable(text: str) -> str:
    """Text as compared with a quote: punctuation folded, case and whitespace ignored."""
    return _flat(fold_punctuation(join_hyphenated(text))).casefold()


def _period_clause(sentence: str) -> str:
    """The clause of ``sentence`` that states its period (the whole sentence when none or several do)."""
    parts = _CLAUSE.split(sentence)
    with_period = [part for part in parts if _periods(part).found]
    return with_period[0] if len(with_period) == 1 else sentence


def _negation_scope(sentence: str, text: str, own: bool) -> str:
    """Where a "Widerspruch ist nicht möglich" counts: the clause holding the period only when that clause names
    a remedy of its own ("…, vielmehr kann … Klage …"); otherwise the whole sentence (or the notice's text)."""
    if not own:
        return text
    clause = _period_clause(sentence)
    return clause if clause != sentence and _REMEDY.search(clause) else sentence


def _remedy(sentence: str) -> str:
    """The remedy a notice names: from the clause that holds its period, else from the whole sentence — never a
    decision on a remedy ("Widerspruchsbescheid", "über Ihren Einspruch") or a procedure skipped."""
    found = _REMEDY.search(_DECISION_ON_REMEDY.sub(" ", _period_clause(sentence))) or _REMEDY.search(
        _DECISION_ON_REMEDY.sub(" ", sentence)
    )
    word = found.group().casefold() if found else ""
    return next((remedy for stem, remedy in _REMEDIES if word.startswith(stem)), "objection")


class _Periods(NamedTuple):
    good: tuple[tuple[int, Unit], ...]  # days, weeks or months, more than nothing
    odd: bool  # a period that can't be read or counted (Werktage, years, none at all, "Kalendermonat")

    @property
    def found(self) -> bool:
        return bool(self.good) or self.odd


def _periods(text: str) -> _Periods:
    words = _MONTH_PERIOD.sub("einen Monat", text)
    read = parse_periods(words)
    good = tuple((amount, _UNITS[unit]) for amount, unit in read if unit in _UNITS and amount > 0)
    odd = any(unit not in _UNITS or amount <= 0 for amount, unit in read) or bool(_ODD_PERIOD.search(words))
    return _Periods(good, odd)


def _own_lines(text: str) -> str:
    """The notice's own lines: from the first that names a remedy or a period (not a heading or the letter's
    header run into it for want of a full stop)."""
    lines = text.split("\n")
    first = next(
        (index for index, line in enumerate(lines) if _REMEDY.search(line) or _PERIOD_WORDS.search(line)), 0
    )
    # the line the sentence wrapped from ("Gegen den Bescheid vom 08.10.2026 können Sie innerhalb"): a line of
    # more than three words that ends without a comma, colon or semicolon (not a heading, a salutation or a label),
    # or any such line the sentence goes on from ("Gegen den Bescheid" / "vom 01.10.2026 können Sie …")
    while (
        first > 0
        and (len(lines[first - 1].split()) > 3 or _CONTINUED.match(lines[first]))
        and not lines[first - 1].rstrip().endswith((",", ":", ";"))
    ):
        first -= 1
    return "\n".join(lines[first:])


def _window(text: str) -> str | None:
    """The notice's words as a quote: all of its own lines when short, else the stretch from its remedy word
    to its periods with what fits around it, up to :data:`QUOTE_CAP`; ``None`` when that stretch alone is
    longer."""
    text = _own_lines(text)
    flat = _flat(text)
    if len(flat) <= QUOTE_CAP:
        return flat
    remedy = _REMEDY.search(text)
    marks = [match.span() for match in _PERIOD_WORDS.finditer(text)]
    if remedy is not None:
        marks.append(remedy.span())
    if not marks:
        return None
    low, high = min(start for start, _ in marks), max(end for _, end in marks)
    if high - low > QUOTE_CAP:
        return None
    room = (QUOTE_CAP - (high - low)) // 2
    start, end = max(0, low - room), min(len(text), high + room)
    while start > 0 and not text[start - 1].isspace() and start < low:
        start += 1
    while end < len(text) and not text[end].isspace() and end > high:
        end -= 1
    quote = _flat(text[start:end])
    return quote if len(quote) <= QUOTE_CAP else None


def _issued(text: str, patterns: tuple[re.Pattern[str], ...] | None = None) -> tuple[date, ...]:
    """The dates of the decisions the notice's own lines name ("Gegen den Bescheid vom 01.10.2026 …"), also
    when its first line wrapped ("Gegen den Bescheid vom 08.10.2026 können Sie innerhalb" / "eines Monats …")
    — not the one this letter reshapes ("Bescheid vom … in Gestalt dieses Widerspruchsbescheids": its period
    runs from this letter). ``patterns``: what precedes such a date (default: a decision's noun)."""
    days: list[date] = []
    pairs = (
        ((_own_lines(text), _ISSUED), (text, _AGAINST_ISSUED)) if patterns is None else ((text, patterns[0]),)
    )
    for part, pattern in pairs:
        folded = fold_punctuation(part)
        days += [
            day
            for start, end, mention in date_spans(folded)
            if not mention.ambiguous
            and (day := mention.as_date()) is not None
            and pattern.search(folded[:start])
            and not _RESHAPED.match(folded[end:])
        ]
    return tuple(dict.fromkeys(days))


def remedy_notices(pages: Sequence[PageInput]) -> list[RemedyNotice]:
    """Every sentence of the visible text naming a remedy (Widerspruch, Einspruch, Klage, objection, appeal)
    with a period in it or in the sentence after it — that one only when it names neither a remedy nor a
    payment. Words split across lines are joined as quotes are matched ("Wider-\\nspruch"); "Monatsfrist" is
    one month. A notice whose period can't be read, or counts back from an event without a start from this
    letter, is kept but can't be dated (:attr:`RemedyNotice.datable`)."""
    found: list[RemedyNotice] = []
    for page in pages:
        folded = sentences(join_hyphenated(_visible(page)))
        for index, sentence in enumerate(folded):
            if not _REMEDY.search(sentence):
                continue
            following = folded[index + 1] if index + 1 < len(folded) else ""
            foldable = bool(following) and not _REMEDY.search(following) and not _PAYMENT.search(following)
            own = _periods(sentence)
            after = _periods(following) if foldable else _Periods((), False)
            if not own.found and not after.found:
                continue
            text = f"{sentence} {following}" if foldable else sentence
            # the sentence after counts for the date whenever it may go on about the period (the shorter wins),
            # but for the check to fire only when the notice has no period of its own and it names its start
            alone = sentence if own.found else text
            backward = bool(_BACKWARD.search(text)) and not _FORWARD.search(text)
            handled = _HANDLED.search(alone) and not _FORWARD.search(alone) and not _LODGED.search(alone)
            quote = _window(text)
            found.append(
                RemedyNotice(
                    quote=quote if quote is not None else _flat(sentence)[:QUOTE_CAP],
                    text=_flat(text),
                    periods=(*own.good, *after.good),
                    notified=bool(_NOTIFIED.search(text)) and not _ARRIVAL.search(text),
                    remedy=_remedy(sentence),
                    live=bool(_REMEDY.search(_CONTRADICTORY.sub(" ", sentence)))
                    and not _NOT_LIVE.search(alone)
                    and not handled  # the person's own objection being dealt with
                    and not _NEGATED.search(_negation_scope(sentence, text, own.found))
                    and not backward  # counted back from an event (a hearing): no deadline from this letter
                    and (own.found or bool(_LIVE_FOLD.search(following))),
                    # counted back from an event: never dated forward, whatever start words it also has
                    datable=not (own.odd or (not own.found and after.odd))
                    and not _BACKWARD.search(text)
                    and quote is not None,
                    issued=_issued(text),
                    grounding=_grounding(page),
                    stated=own.good if own.found else after.good,
                    mentioned=_issued(_own_lines(text), (_LETTER_ISSUED,)),
                )
            )
    return found


def _blank(details: ExtractedContract | ExtractedChange | PaymentDetails | None) -> bool:
    """A part of the reading that is absent, or holds nothing but its defaults and empty values (a contract's
    required name left blank)."""
    if details is None:
        return True
    dump = details.model_dump(exclude_defaults=True)
    return not any(value.strip() if isinstance(value, str) else value for value in dump.values())


def _empty(extraction: DocumentExtraction) -> bool:
    sender = extraction.sender
    remedy = extraction.remedy
    return (
        not extraction.items
        and (sender is None or not sender.name.strip())
        and not extraction.document_date
        and not extraction.key_facts
        and not extraction.references
        and all(_blank(details) for details in (extraction.contract, extraction.change, extraction.payment))
        and (remedy is None or remedy.type == "none")
    )


def _iso(value: str | None) -> date | None:
    """An ISO date as the rules engine reads one (``rules.deadlines.parse_date``)."""
    try:
        return date.fromisoformat(value.strip()[:10]) if value else None
    except ValueError:
        return None


def _computable(spec: DateSpec, dated: bool = True) -> bool:
    """Whether a DateSpec gives a date the engine can compute in the letter's context (a model's objection
    item without one doesn't count as dating the objection): a period from the letter's date, its delivery or
    its arrival needs the letter's date (``dated``: the reading gives one)."""
    if spec.type == "fixed":
        return _iso(spec.date) is not None
    if spec.type != "relative" or spec.amount is None or spec.unit is None:
        return False
    if spec.anchor == "explicit_date":
        return _iso(spec.anchor_date) is not None
    return spec.anchor == "today" or dated


def dates_the_objection(
    item: ExtractedItem,
    notices: Sequence[RemedyNotice],
    extraction: DocumentExtraction | None = None,
    *,
    dated: bool = True,
) -> bool:
    """A to-do of the reading that dates the objection: an objection with a date, or any dated to-do whose
    quote is part of a notice's words (an objection filed under another nature) — never a payment, one with
    no quote, or one whose date doesn't compute in the letter's context (``dated``: a period from the letter's
    date, its delivery or arrival computes — the reading gives that date, or the letter gives none the check
    could count from), nor one § 574b BGB would count back from a tenancy's end (``extraction``: the reading,
    for its kind; it gives no date here)."""
    if not _computable(item.date, dated):
        return False
    letter = letter_kind(extraction) if extraction is not None else None
    if item.date.type == "relative" and special_rule(item.date, letter, authority=True) == "bgb_574b":
        return False  # counted back from a tenancy's end the letter doesn't name: no date
    if item.date.nature == "objection":
        return True
    if item.kind == "payment" or item.date.nature == "payment":
        return False
    quote = _matchable(item.quote)
    return bool(quote) and any(quote in _matchable(notice.text) for notice in notices)


def _law_dated(extraction: DocumentExtraction, notices: Sequence[RemedyNotice], text: str) -> bool:
    """A kind of letter whose deadline the law files itself — when the letter's own words bear it out, or its
    notices give no shorter period than the law (so a reading's laundered kind never brings a later date)."""
    kind = letter_kind(extraction)
    if kind not in LAW_DATED_KINDS:
        return False
    if all(words.search(text) for words in _LAW_WORDS[kind]):
        return True
    law = _LAW_DAYS.get(kind)
    shortest = min(
        (
            amount * {"days": 1, "weeks": 7, "months": 28}[unit]
            for notice in notices
            for amount, unit in notice.periods
        ),
        default=None,
    )
    return law is not None and shortest is not None and shortest >= law


def reading_gap(
    extraction: DocumentExtraction, pages: Sequence[PageInput], notices: Sequence[RemedyNotice]
) -> Gap | None:
    """Why the reading is incomplete (module docstring), or ``None``. Its warnings, kind, title, summary and
    explanation are never looked at. A left-out objection counts only with a live notice
    (:attr:`RemedyNotice.live`), on a letter whose visible text shows an administrative act
    (:func:`~ordnung.rules.delivery.shows_administrative_act`: not a direct debit's or a contract's right to
    object), not filed as a kind the law dates itself (:func:`_law_dated`), and only when no to-do dates the
    objection (:func:`dates_the_objection`) — a ``remedy`` the reading copied without its date doesn't count."""
    if _empty(extraction):
        return "empty"
    text = "\n".join(_visible(page) for page in pages)
    # an objection counted from the letter's date the reading left out computes only when the letter gives none
    dated = _iso(extraction.document_date) is not None or _start(extraction, pages, notices).day is None
    if _objection_due(extraction, notices, text) and not any(
        dates_the_objection(item, notices, extraction, dated=dated) for item in extraction.items
    ):
        return "remedy_left_out"
    return None


def _objection_due(extraction: DocumentExtraction, notices: Sequence[RemedyNotice], text: str) -> bool:
    """Whether the letter's text says an objection to it is due: a live notice, an administrative act, and
    not a kind of letter the law dates itself (:func:`reading_gap`)."""
    return (
        any(notice.live for notice in notices)
        and shows_administrative_act(text)
        and not _law_dated(extraction, notices, text)
    )


class _Dated(NamedTuple):
    """A date the letter gives for itself: ``strong`` when its words name it the letter's own (a "Datum"
    label, a place and date in the header, the reference line), weak otherwise (another "…datum", a date alone,
    a continuation page's)."""

    day: date
    strong: bool


def _header_dates(page: PageInput, *, first: bool = True) -> list[_Dated]:
    """The dates a page gives for its letter, before its remedy notice: one date that reads one way and ends
    its line, after a date label ("Datum 06.11.2026", "Bescheiddatum:", "Einzugsdatum:" — only a label of the
    letter's own date is strong), after a place ("Musterstadt, (den) 06.11.2026"; strong among the header's
    lines, never under a line ending in ":"), on the reference line under a line ending in "Datum" ("Ihr
    Zeichen  Unser Zeichen  Datum" over "AB-1  ST-22  06.11.2026": its last date, strong) or — in the page's
    header, not under a line that labels another date ("Antrag vom") — alone (weak). Never a due day, a
    validity, an appointment or a date after a weekday ("Zahlbar bis Freitag, 04.12.2026"). A remedy word in
    the letterhead or subject ("Widerspruchsstelle") doesn't end the scan; the notice does. On a page after
    the first (``first`` false) every date is weak."""
    lines = fold_punctuation(join_hyphenated(_visible(page))).splitlines()
    rows = len(header(lines))
    found: list[_Dated] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _GERMAN_REMEDY.search(stripped) and (index >= rows or _PERIOD_WORDS.search(stripped)):
            break  # the notice: what follows is no date of the letter's (a sign-off, an enclosure's)
        spans = date_spans(stripped)
        previous = lines[index - 1].strip() if index else ""
        if spans and index and index - 1 <= rows and _REFERENCE_LABELS.search(previous):
            start, end, mention = spans[-1]
            day = mention.as_date()
            if day is not None and end == len(stripped):
                found.append(_Dated(day, first))
            continue
        if len(spans) != 1:
            continue
        start, end, mention = spans[0]
        day = mention.as_date()
        if day is None or end != len(stripped):
            continue
        before = stripped[:start]
        if _DATE_LABEL.search(before):
            other = _OTHER_DATE.search(
                _CREATED_ON.sub(" ", before)
            )  # "Fälligkeitsdatum:" is no letter's date
            strong = bool(_OWN_LABEL.search(before))
        elif _PLACE_DATE.match(before):
            other = _OTHER_DATE.search(before)  # "Zahlbar bis Freitag, …"
            strong = index < rows and not previous.endswith(":")
        elif not before.strip() and index < rows:
            other = _ANOTHER.search(previous) or _OTHER_DATE.search(previous)  # under "Antrag vom", "Termin:"
            strong = False
        else:
            continue
        if other is None:
            found.append(_Dated(day, strong and first))
    return found


class _Start(NamedTuple):
    """The start the letter's dates give (``None``: none they agree on) and whether it gives any date at all."""

    day: date | None
    found: bool


def letter_date(
    extraction: DocumentExtraction,
    pages: Sequence[PageInput],
    notices: Sequence[RemedyNotice] | None = None,
    *,
    today: date | None = None,
) -> date | None:
    """The letter's date to count from (:func:`_start`): ``None`` when there is none to rely on."""
    return _start(extraction, pages, notices, today=today).day


def _start(
    extraction: DocumentExtraction,
    pages: Sequence[PageInput],
    notices: Sequence[RemedyNotice] | None,
    *,
    today: date | None = None,
) -> _Start:
    """The earliest date the letter gives for itself, never later than its own date:

    * **strong** dates set it: the reading's, the first page's "Datum:" and "mit diesem Bescheid vom …"
      (:func:`~ordnung.ingest.conflicts.letter_statements`), the first page's own header date named as the
      letter's (:func:`_header_dates`) and the decision its notice names ("Bescheid vom …"). None when there is
      none, or when they are more than :data:`LETTER_DATE_SPAN` days apart (one of them is another's: planted,
      a due day, an old decision's);
    * **weak** dates (another "…datum", a date alone, a continuation page's, "Schreiben vom …") only lower it,
      within that span of the strong ones — one earlier still leaves no start, as two strong ones would; one
      later than every strong date is another's and is ignored;
    * a start that rests on one date alone, more than :data:`STALE_DAYS` before ``today`` (the day the letter
      arrived, or was read), is no start: never an overdue to-do from a stray date."""
    strong, weak = _letter_dates(extraction, pages, notices)
    found = bool(strong or weak)
    if not strong:
        return _Start(None, found)
    first, last = min(strong), max(strong)
    if (last - first).days > LETTER_DATE_SPAN:
        return _Start(None, found)
    earlier = [day for day in weak if day < first]
    if any((last - day).days > LETTER_DATE_SPAN for day in earlier):
        return _Start(None, found)
    first = min([first, *earlier])
    alone = len({*strong, *weak}) == 1
    if alone and today is not None and (today - first).days > STALE_DAYS:
        return _Start(None, found)
    return _Start(first, found)


def _letter_dates(
    extraction: DocumentExtraction, pages: Sequence[PageInput], notices: Sequence[RemedyNotice] | None
) -> tuple[list[date], list[date]]:
    """The letter's strong and weak dates for itself, the reading's among the strong (:func:`_start`)."""
    strong = [statement.letter_date for statement in letter_statements(pages) if statement.letter_date]
    weak: list[date] = []
    for index, page in enumerate(pages):
        for dated in _header_dates(page, first=index == 0):
            (strong if dated.strong else weak).append(dated.day)
    for notice in notices if notices is not None else remedy_notices(pages):
        strong += notice.issued
        weak += notice.mentioned
    read = _iso(extraction.document_date)
    return ([*strong, read] if read is not None else strong), weak


def _own_start(pages: Sequence[PageInput]) -> date | None:
    """The date the letter's first page names as its own (a "Datum" label, a place and date in its header, the
    reference line, "mit diesem Bescheid vom …"), never the reading's, a bare or a continuation page's date:
    the earliest when they are within :data:`LETTER_DATE_SPAN` days, else the latest."""
    days = [statement.letter_date for statement in letter_statements(pages[:1]) if statement.letter_date]
    days += [dated.day for dated in (_header_dates(pages[0]) if pages else []) if dated.strong]
    if not days:
        return None
    return min(days) if (max(days) - min(days)).days <= LETTER_DATE_SPAN else max(days)


def _end(start: date, period: tuple[int, Unit]) -> date:
    """The last day of ``period`` counted from ``start`` (§ 188 BGB, no weekends): to rank periods."""
    amount, unit = period
    if unit != "months":
        return start + timedelta(days=amount * _DAYS[unit])
    month = start.month - 1 + amount
    year, month = start.year + month // 12, month % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _datable(period: tuple[int, Unit]) -> bool:
    amount, unit = period
    return amount <= _DATABLE_MAX[unit] and amount * _DAYS[unit] >= _DATABLE_MIN_DAYS


class _Choice(NamedTuple):
    notice: RemedyNotice
    period: tuple[int, Unit] | None  # None: no date can be worked out
    delivery: Literal["de_admin_post", "de_admin_portal", "none"]


def _choose(notices: Sequence[RemedyNotice], start: date | None, text: str) -> _Choice:
    """The notice whose period ends first, counted from the letter's date ``start`` (a court action after the
    other remedies, then one without delivery days, on a tie), and how it counts:

    * no date when any notice can't be dated, the period isn't from a week to a month, or the order of two
      periods near a month depends on a start Ordnung doesn't know;
    * delivery days only when every notice counts from notification and its period ends first from any start
      deemed delivery can give — by portal when the letter says so, never on formal service."""
    ranked = [(notice, period) for notice in notices for period in notice.periods]
    if not ranked:
        return _Choice(min(notices, key=lambda n: (n.remedy == "klage", n.notified)), None, "none")

    def order(start_day: date | None, pick: tuple[RemedyNotice, tuple[int, Unit]]) -> tuple[object, ...]:
        notice, period = pick
        length = _end(start_day, period) if start_day else period[0] * _DAYS[period[1]]
        return length, period[0] * _DAYS[period[1]], notice.remedy == "klage", notice.notified

    notice, period = min(ranked, key=lambda pick: order(start, pick))
    near_month = any(unit == "months" for _, (_, unit) in ranked) and any(
        unit == "days" and 28 < amount <= 31 for _, (amount, unit) in ranked
    )
    if not all(n.datable for n in notices) or not _datable(period) or (start is None and near_month):
        return _Choice(notice, None, "none")
    # from any start deemed delivery can give, the chosen period still ends first (or there is no start yet)
    first_whatever_the_start = start is None or all(
        _end(start + timedelta(days=shift), period) <= _end(start + timedelta(days=shift), other)
        for shift in range(_DELIVERY_REACH + 1)
        for _, other in ranked
    )
    delivery: Literal["de_admin_post", "de_admin_portal", "none"] = "none"
    if all(n.notified for n in notices) and not _FORMAL_SERVICE.search(text) and first_whatever_the_start:
        delivery = "de_admin_portal" if _PORTAL.search(text) else "de_admin_post"
    return _Choice(notice, period, delivery)


def check_item(
    extraction: DocumentExtraction,
    pages: Sequence[PageInput],
    *,
    injected: bool = False,
    today: date | None = None,
) -> Check | None:
    """The to-do an incomplete reading gets (module docstring), why, which kind it is and its remedy; ``None``
    for a complete reading. ``injected``: the letter carries text addressed to an AI — and for an almost blank
    reading, which is itself such a sign — the action says where to send the objection. ``today``: the day the
    letter arrived or is read (a start resting on one date long before it is none: :func:`_start`).

    With a remedy notice, a ``deadline``: the period of :func:`_choose`, counted from the letter's date
    (:func:`letter_date`, carried in the DateSpec's ``anchor_date``, so it computes without a date in the
    reading and keeps it when recomputed; when neither the letter nor the reading gives any date, from the
    letter's date once the person enters it) — or without a date (``DateSpec(type="none")``) when none can
    be worked out, also when the letter's dates for itself disagree (never from the later one stored).
    Without one, a ``task``: read the letter."""
    notices = remedy_notices(pages)
    gap = reading_gap(extraction, pages, notices)
    if gap is None:
        return None
    if not notices:
        placeholder = ExtractedItem(
            kind="task",
            title="Read this letter yourself",
            action=PLACEHOLDER_ACTION,
            date=DateSpec(type="none"),
            priority="high",
            quote="",
        )
        return Check(gap, placeholder, "read_yourself", "")
    start = _start(extraction, pages, notices, today=today)
    written = start.day
    notice, period, delivery = _choose(notices, written, "\n".join(_visible(page) for page in pages))
    if written is None and start.found:
        period = (
            None  # the letter's dates disagree, or none names itself: no start, never the one stored later
        )
    kind: CheckKind
    if period is None:
        spec = DateSpec(type="none", nature="objection", text=notice.quote)
        kind = "undated"
    else:
        spec = DateSpec(
            type="relative",
            anchor="explicit_date" if written else "document_date",
            anchor_date=written.isoformat() if written else None,
            amount=period[0],
            unit=period[1],
            delivery_rule=delivery,
            shift_rule="auto",
            nature="objection",
            text=notice.quote,
        )
        kind = "dated" if written else "undated"
    court = notice.remedy == "klage"
    action = KLAGE_ACTION if court else DEADLINE_ACTION
    deadline = ExtractedItem(
        kind="deadline",
        title=_TITLES.get(notice.remedy, "Deadline to object"),
        action=f"{action} {KNOWN_ADDRESS}" if injected or gap == "empty" else action,
        consequence=KLAGE_CONSEQUENCE if court else DEADLINE_CONSEQUENCE,
        date=spec,
        priority="high",
        quote=notice.quote,
    )
    return Check(gap, deadline, kind, notice.remedy)


def notice_rival(
    extraction: DocumentExtraction, pages: Sequence[PageInput], notices: Sequence[RemedyNotice] | None = None
) -> Rival | None:
    """The objection deadline the letter's own notice gives, as a second date for a to-do of the reading that
    dates the objection (:func:`dates_the_objection`): :func:`~ordnung.ingest.plan.compute_item` sets it beside
    that to-do's own date when it ends more than :data:`NOTICE_REACH` days earlier, or when the reading's period
    is longer than the notice's — then the earlier is kept, both are named and the to-do is "Please check"
    (:func:`~ordnung.ingest.conflicts.settle`).

    Decided on the letter's words alone, never the reading's: a live, datable notice on an administrative act
    (a kind of letter the law dates itself only when its words bear that kind out); the period that ends first
    of those the live notices' own sentences state (never an instruction folded in after one, nor a notice
    that can't be dated: a planted "ein Jahr" never switches it off); counted from the date the letter's first
    page names as its own (:func:`_own_start`), never the reading's date or a stray one — no first-page date,
    no rival."""
    notices = remedy_notices(pages) if notices is None else notices
    text = "\n".join(_visible(page) for page in pages)
    kind = letter_kind(extraction)
    borne_out = kind in LAW_DATED_KINDS and all(words.search(text) for words in _LAW_WORDS[kind])
    live = [notice for notice in notices if notice.live and notice.datable]
    if not live or borne_out or not shows_administrative_act(text):
        return None
    start = _own_start(pages)
    picks = [(notice, period) for notice in live for period in notice.stated if _datable(period)]
    if start is None or not picks:
        return None
    # the period that ends first; on a tie the one with the delivery days (never an earlier date than it says)
    notice, period = min(picks, key=lambda pick: (_end(start, pick[1]), not pick[0].notified))
    delivery: Literal["de_admin_post", "de_admin_portal", "none"] = "none"
    if notice.notified and not _FORMAL_SERVICE.search(text):
        delivery = "de_admin_portal" if _PORTAL.search(text) else "de_admin_post"
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=start.isoformat(),
        amount=period[0],
        unit=period[1],
        delivery_rule=delivery,
        shift_rule="auto",
        nature="objection",
    )
    return Rival(spec, notice.quote, notice.grounding, notice=True)


def gap_warning(gap: Gap, kind: CheckKind, remedy: str = "") -> str:
    """The letter's warning for an incomplete reading: why (``gap``; a court action's own words for a
    ``klage`` notice the reading left out), then what Ordnung did (``kind``)."""
    prefix = _COURT_PREFIX if gap == "remedy_left_out" and remedy == "klage" else _PREFIX[gap]
    return f"{prefix} {_SUFFIX[kind]}"


#: The letter's warning for an incomplete reading (:func:`gap_warning`), whatever its kind.
GAP_WARNING = re.compile(
    r"^(?:Claude's reading of this letter came back almost blank|This letter explains how to (?:object|challenge it "
    r"in court), but Claude's reading)"
)


def square_gap_warnings(warnings: Sequence[str], items: Sequence[Any]) -> list[str]:
    """The letter's warnings with the one about an incomplete reading in step with the to-do Ordnung added for
    it (``items``: the letter's stored to-dos): gone once that to-do no longer needs checking (confirmed,
    re-dated, done, dismissed or deleted), and saying the deadline was added once it has a date (the person
    entered the letter's date) rather than "couldn't work out the deadline"."""
    from ordnung.ingest.plan import needs_check

    checks = [item for item in items if item.slot_key == CHECK_SLOT]
    pending = [item for item in checks if needs_check(item)]
    kept: list[str] = []
    for warning in warnings:
        if not GAP_WARNING.match(warning.strip()):
            kept.append(warning)
        elif pending:
            dated = any(item.due_date for item in pending)
            kept.append(warning.replace(_SUFFIX["undated"], _SUFFIX["dated"]) if dated else warning)
    return kept


def check_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    """The reasons the code-made to-do is graded by: always :data:`READING_INCOMPLETE`; never that its quote
    doesn't state the start date or the period (Ordnung took them from the letter, not from that sentence)."""
    kept = tuple(reason for reason in reasons if reason not in (DATE_NOT_IN_QUOTE, PERIOD_NOT_IN_QUOTE))
    return kept if READING_INCOMPLETE in kept else (*kept, READING_INCOMPLETE)


def start_variants(spec: DateSpec, ctx: RuleContext) -> list[tuple[DateSpec, RuleContext]]:
    """The code-made to-do's DateSpec (first) and the same period from every earlier start the letter's dates
    as stored allow — the letter's date the person corrected, an arrival confirmed before the date (for a
    period from service or arrival), the stored letter date when it had none — each in a context that never
    routes it through a letter rule meant for the model's readings (§ 574b BGB would read the start as the
    tenancy's end). The earliest of their dates is the to-do's: recomputing never moves it later."""
    plain = ctx
    if special_rule(spec, ctx.letter_kind, authority=ctx.delivery_scope is not None or ctx.court) is not None:
        spec = spec.model_copy(update={"text": "", "legal_basis": None})
        plain = replace(ctx, letter_kind=None)
    variants = [(spec, plain)]
    if spec.type != "relative":
        return variants
    start = _iso(spec.anchor_date) if spec.anchor == "explicit_date" else None
    stored = ctx.document_date
    if spec.anchor == "explicit_date" and start is None:
        variants.append((spec.model_copy(update={"anchor": "document_date", "anchor_date": None}), plain))
    if start is not None and stored is not None and stored < start:
        variants.append((spec.model_copy(update={"anchor_date": stored.isoformat()}), plain))
    arrival = ctx.received_date if ctx.received_confirmed else None
    if (
        start is not None
        and arrival is not None
        and arrival < start
        and (spec.delivery_rule == "none" or ctx.private_sender)
    ):
        variants.append((spec.model_copy(update={"anchor_date": arrival.isoformat()}), plain))
    return variants
