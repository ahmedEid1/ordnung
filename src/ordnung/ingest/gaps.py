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

import bisect
import calendar
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Literal, NamedTuple

from ordnung.ingest.conflicts import (
    _BLOCK_ABOVE,
    _BLOCK_BELOW,
    _EVENT,
    _SALUTATION,
    _SENTENCE_END,
    Rival,
    _clauses,
    find_rivals,
    header,
    letter_statements,
    sentences,
)
from ordnung.ingest.normalize import fold_punctuation, join_hyphenated
from ordnung.ingest.text import PageText
from ordnung.ingest.verify import (
    DATE_NOT_IN_QUOTE,
    DEADLINE_LEFT_OUT,
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
from ordnung.rules.delivery import scope_for_party_kind, shows_administrative_act
from ordnung.rules.routing import letter_kind, special_rule

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


_REMEDY = re.compile(
    r"widerspr\w*|einspr\w*|\bklage\w*|\b(?:anfechtungs|verpflichtungs)klage\w*|\bobjection\w*|\bobject\b|\bappeal\w*",
    re.IGNORECASE,
)
_GERMAN_REMEDY = re.compile(
    r"widerspr\w*|einspr\w*|\bklage\w*|\b(?:anfechtungs|verpflichtungs)klage\w*", re.IGNORECASE
)
#: The decision a remedy was already lodged against names no remedy: "in Gestalt dieses Widerspruchsbescheids
#: kann … Klage …", "ohne Widerspruchsverfahren … Klage", "über Ihren Einspruch … Klage" are court actions.
_DECIDED_REMEDY = re.compile(r"widerspruchsbescheid|einspruchsentscheidung", re.IGNORECASE)
#: The letter names itself a decision on a remedy: "dieser Widerspruchsbescheid", or a heading line "Widerspruchsbescheid",
#: "Teilabhilfe- und Widerspruchsbescheid (vom …)".
_SELF_DECIDED = re.compile(
    r"\bdiese[nmrs]?\s+(?:\w+\s+)?(?:widerspruchsbescheid|einspruchsentscheidung)"
    r"|^\s*(?:[\w-]+\s+und\s+)?(?:widerspruchsbescheid|einspruchsentscheidung)\w*\b(?:[^.;,\n]|\.(?=\d)){0,40}$",
    re.IGNORECASE | re.MULTILINE,
)
#: A live objection notice on this letter itself ("Gegen diesen Bescheid kann … Widerspruch …", "… nach Bekanntgabe
#: dieses Bescheides einzulegen"): a first-instance decision, whatever it says of a later Widerspruchsbescheid.
_THIS_FIRST_DECISION = re.compile(
    r"\bdiese[nmrs]?\s+(?!widerspruchs|einspruchs)(?:\w+\s+)?\w*(?:bescheid|festsetzung|verfügung)",
    re.IGNORECASE,
)
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
#: the remedy, or the account holder's right "der Lastschrift … zu widersprechen"), a hint at a court action
#: for inaction, or one on a decision not yet made ("gegen einen Bescheid", "gegen eine Ablehnung", "sollten
#: wir …", "könnten Sie", "erst gegen den Bescheid") — only whether the check fires: never its date.
_NOT_LIVE = re.compile(
    r"(?:späteren|künftigen)\s+\w*bescheid|\bhätten\b|\beingelegt\s+haben\b|"
    r"\b(?:ist|sind|wurde|wurden)\s+(?:(?!wenn\b|sofern\b|falls\b|soweit\b|ob\b|dass\b|sobald\b|wann\b)\S+\s+){0,4}?eingegangen\b|"
    r"\bbegründen\s+Sie\s+(?:Ihren|Ihre|die|den)\s+(?:widerspruch|einspruch|klage)|"
    r"lastschrift\W+(?:\w+\W+){0,2}widersprech|(?:widerspr|einspr)\w*\W+(?:\w+\W+){0,2}lastschrift|"
    r"\bkein(?:en)?\s+(?:neuer\s+)?(?:bescheid|verwaltungsakt)\b|"
    r"untätigkeitsklage|\bgegen\s+(?:einen|eine|ein)\s+"
    r"(?:(?:ablehnend|negativ|etwaig|eventuell|möglich|später|künftig|neu|weiter|erneut)\w*\s+){0,2}\w*(?:bescheid|entscheidung|ablehnung|versagung|aufhebung"
    r"|rückforderung|festsetzung|verfügung)|\bsollten\s+wir\b|\bkönnten\s+sie\b|\berst\s+gegen\s+(?:den|die|das|einen|eine|ein)\b|"
    # a decision still to come: "gegen eine spätere Verfügung", "den dann ergehenden Bescheid", "nach Erlass des Bescheides"
    r"\b(?:spätere[nmrs]?|künftige[nmrs]?|dann\s+ergehende[nmrs]?|(?:noch\s+)?zu\s+erlassende[nmrs]?|beabsichtigte[nmrs]?)\s+"
    r"\w*(?:bescheid|entscheidung|verfügung|festsetzung)|\bnach\s+(?:dem\s+)?erlass\s+(?:des|der|eines|einer)\b|\bnach\s+deren\s+erlass\b|"
    r",\s+(?:der|die|das)\s+(?:\w+\s+){0,6}?ergeh(?:t|en\s+wird)\b|"
    # the data-protection right to object (Art. 21 DSGVO) and a direct debit's refund named without "Lastschrift"
    r"\bart\.?\s*21\s+(?:abs\.?\s*\d\s+)?ds-?gvo\b|\bgegen\s+die\s+(?:weitere\s+)?verarbeitung\b|"
    r"\b(?:der|die)\s+verarbeitung\s+(?:\w+\s+){0,4}?widersprech|\bwiderspruchsrecht\s+(?:nach|gemäß)\s+art|"
    r"\b(?:abbuchung|belastung|bankeinzug|einzug)\b[^.;:]{0,80}?\bwidersprech|\bwidersprech\w*[^.;:]{0,40}?\b(?:abbuchung|belastung)\b|"
    r"\bbelastungsdatum\b",
    re.IGNORECASE,
)
#: The account holder's right against a direct debit: "der Lastschrift innerhalb von acht Wochen … widersprechen" —
#: unless this decision is what is objected to ("diesem Bescheid … widersprechen, auch wenn Sie am
#: Lastschriftverfahren teilnehmen"), with no debit named between the two.
_DEBIT_RIGHT = re.compile(
    r"lastschrift[^.;:]{0,80}?\bwidersprech|\bwidersprech\w*[^.;:]{0,40}?\blastschrift", re.IGNORECASE
)
_DECISION_OBJECTED = re.compile(
    r"\bdiese[mn]\s+(?:\w+\s+)?\w*bescheid\w*\s+(?:(?!lastschrift|abbuchung|einzug|belastung|abgebucht|eingezogen)[^.;:]){0,80}?"
    r"\bwidersprech",
    re.IGNORECASE,
)
_DEBIT_OBJECTED = re.compile(
    r"\b(?:der|einer|jeder|dieser)\s+(?:sepa-)?lastschrift\w*\s+[^.;:]{0,80}?\bwidersprech", re.IGNORECASE
)


def _debit_right(text: str) -> bool:
    return bool(_DEBIT_RIGHT.search(text)) and not (
        _DECISION_OBJECTED.search(text) and not _DEBIT_OBJECTED.search(text)
    )


#: "Wenn Sie Widerspruch einlegen, …": another's period — unless the sentence counts from this letter ("…, muss
#: dieser innerhalb eines Monats nach Bekanntgabe eingehen").
_TAKEN_AS_LODGED = re.compile(
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
    r"(?<!telefonisch )(?<!mündlich )(?<!elektronisch )(?<!schriftlich )(?<!e-mail )(?<!email )(?<!fax )"
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
    r"einlegung|erhebung|eingegangen\s+sein|eingehen|"
    r"\bihren\s+(?:widerspruch|einspruch)\s+(?:\w+\s+){0,2}?(?:senden|richten|schicken|reichen)\s+sie\b",
    re.IGNORECASE,
)
#: A sentence about paying ("Trotz eines Widerspruchs ist der Betrag innerhalb von zwei Wochen zu zahlen", "Die Kosten
#: des Widerspruchsverfahrens sind …zu zahlen") that names no way of lodging a remedy is no notice.
_PAYS = re.compile(
    r"\bzu\s+(?:zahlen|überweisen|entrichten|begleichen)\b|\b(?:zahlen|überweisen)\s+sie\b|\bfällig\b|\bzahlbar\b",
    re.IGNORECASE,
)
#: Words of how a remedy is lodged or open ("einlegen", "Widerspruchsfrist", "möglich"): a sentence naming money
#: and one of these is still a notice ("Gegen diesen Zahlungsbescheid ist … der Widerspruch möglich").
_LODGES = re.compile(
    r"erheb|erhob|einleg|eingeleg|einzuleg|einreich|eingereich|einzureich|widersprech|widersproch|einlegung|erhebung|"
    r"eingegangen\s+sein|eingehen|(?:widerspruchs|einspruchs|klage|rechtsbehelfs)frist|zulässig|statthaft|gegeben|anfecht|"
    r"angefochten|möglich",
    re.IGNORECASE,
)

#: A notice about another decision, named without "dies-" and without a date of its own ("Gegen den
#: Gebührenbescheid kann …"): the dates the letter gives that decision elsewhere ("mit Gebührenbescheid vom …").
_ANOTHER_DECISION = re.compile(
    r"\b(?:gegen\s+(?:den|die|das|ihren|ihre)|(?:bekanntgabe|zustellung)\s+(?:des|der|ihres|ihrer))\s+(?:[\w.]+\s+){0,3}?"
    r"\w*(?:bescheid|festsetzung|entscheidung|verfügung)"
    # the sentence cut after an abbreviation ("Gegen den o. g." / "Bescheid kann …"): it starts with the decision
    r"|^\s*\w*(?:bescheid|festsetzung|entscheidung|verfügung)\w*\b",
    re.IGNORECASE,
)
#: A notice naming another decision by a compound noun or a back-reference ("Gegen den Steuerbescheid", "Gegen den
#: o. g." / "Bescheid"): never a bare "Gegen den Bescheid", which a decision says of itself.
_AGAINST_NAMED = re.compile(
    r"\bgegen\s+(?:den|die|das|ihren|ihre)\s+(?:(?:o\.\s*g\.|oben\s+genannten|genannten|vorgenannten)\s+\w*|\w+)"
    r"(?:bescheid|festsetzung|verfügung)"
    r"|^\s*\w*(?:bescheid|festsetzung|verfügung)\w*\b",
    re.IGNORECASE,
)
#: The letter sends or reminds of another decision ("Ihren Einkommensteuerbescheid", "unseren Gebührenbescheid", "den
#: beigefügten Bescheid", "einen Gebührenbescheid"): a cover letter or a reminder.
_SENDS_DECISION = re.compile(
    r"\b(?:ihre[nms]?|unsere[nms]?|einen|per|mit|beigefügte[nmr]?|beiliegende[nmr]?|anliegende[nmr]?|übersandte[nmr]?|"
    r"zugesandte[nmr]?)\s+(?:\w+\s+)?\w*(?:bescheid|festsetzung|verfügung)",
    re.IGNORECASE,
)
#: The letter reminds of an amount still open ("Zahlungserinnerung", "Mahnung", "die noch offen ist", "offene
#: Forderung"): its "Hiergegen …" may restate the notice of the decision that set it (false alarms MISS-2).
_REMINDS = re.compile(
    r"erinnerung|mahnung|\bnoch\s+(?:offen|nicht\s+(?:bezahlt|beglichen|eingegangen))"
    r"|\boffene[nrs]?\s+(?:forderung|betrag|posten|rechnung)|zahlungseingang",
    re.IGNORECASE,
)
#: The letter decides itself, now ("Ihren Antrag … lehnen wir ab", "Ihr Antrag wird abgelehnt", "für diese Mahnung
#: setzen wir eine Mahngebühr … fest"): its "Hiergegen …" is its own notice, never a reminder's restated one — whatever
#: open amount it mentions ("die noch offene Gebühr").
_DECIDES_NOW = re.compile(
    r"\b(?:lehnen|weisen)\s+wir\b[^.;]{0,160}?\b(?:ab|zurück)\b"
    r"|\bwird\s+(?:hiermit\s+)?(?:abgelehnt|zurückgewiesen|festgesetzt|widerrufen|zurückgenommen|aufgehoben)\b"
    r"|\bsetzen\s+wir\b[^.;]{0,160}?\bfest\b|\bbewilligen\s+wir\b",
    re.IGNORECASE,
)
#: The letter names itself a decision: "mit diesem Bescheid", "dieser Festsetzung", or a heading line "Gebührenbescheid",
#: "Bescheid über …".
_NAMES_ITSELF = re.compile(
    r"\bdiese[nmrs]?\s+(?:\w+\s+){0,2}?\w*(?:bescheid|festsetzung|entscheidung|verfügung)"
    r"|^\s*[\w-]*(?:bescheid|festsetzung|verfügung)\w*\b[^\n.]{0,60}$",
    re.IGNORECASE | re.MULTILINE,
)
#: A notice against "diese Entscheidung/Verfügung …" shows a decision too (a health insurer's "nach Erhalt").
_AGAINST_DECISION = re.compile(
    r"\b(?:gegen|mit)\s+(?:diese[nmrs]?|unsere[nmrs]?)\s+(?:\w+\s+){0,2}?\w*(?:entscheidung|verfügung|anordnung|festsetzung)",
    re.IGNORECASE,
)
#: A sentence that sets only a period for the reasons ("Der Widerspruch sollte innerhalb von vier Wochen … begründet
#: werden"), naming no way of lodging the remedy: no notice.
_REASONS_ONLY = re.compile(r"\bzu\s+begründen\b|\bbegründet\s+(?:werden|sein)\b", re.IGNORECASE)
#: A heading that names the letter a decision ("Bescheid", "Bescheid über …"): no "Bescheid geben".
_DECISION_HEADING = re.compile(
    r"^\s*bescheid(?:\s+(?:über|für|zur|zum|nach)\b[^\n]*)?\s*$", re.IGNORECASE | re.MULTILINE
)
#: A notice that names this letter ("gegen diesen Bescheid", "dieses Schreiben"): its date is this letter's.
_SELF = re.compile(
    r"\bdiese[nmrs]?\s+(?:\w+\s+){0,2}?\w*(?:bescheid|festsetzung|entscheidung|verfügung|schreiben|brief)",
    re.IGNORECASE,
)
#: A period from the remedy's own lodging or from an obstacle's end ("innerhalb von zwei Wochen nach seiner Einlegung
#: begründet", "nach Wegfall des Hindernisses Wiedereinsetzung"): another's period, unless the sentence also counts
#: from this letter.
_OTHER_START = re.compile(
    r"\bnach\s+(?:(?:seiner|ihrer|dessen|deren|der)\s+)?(?:einlegung|erhebung)\b|\bwegfall\s+des\s+hindernisses\b",
    re.IGNORECASE,
)
#: The main clause after "Wenn Sie Widerspruch einlegen," refers back to the remedy ("…, muss dieser …"): the
#: sentence is the notice itself, not an instruction for a remedy taken as lodged.
_REFERS_BACK = re.compile(
    r"(?:einlegen|erheben|einreichen|eingelegt\s+haben|erhoben\s+haben),\s+(?:so\s+)?(?:muss|ist|sind|hat|kann|soll|sollte)\s+"
    r"(?:dieser|diese|er|es|dies|der\s+widerspruch|der\s+einspruch|die\s+klage)\b",
    re.IGNORECASE,
)
#: The main clause after "Wenn Sie Widerspruch einlegen, …" that lodges the remedy ("… eingehen", "… zu senden").
_LODGED_MAIN = re.compile(
    r"eingeh|eingegangen|zugeh|zugegangen|einzuleg|eingelegt|einzureich|eingereicht|zu\s+erheben|erhoben|geschehen|"
    r"erfolgen|zu\s+richten|gerichtet|vorliegen|zu\s+senden|zu\s+schicken|abzugeben|zu\s+erklären|erklärt|ankommen",
    re.IGNORECASE,
)
#: … and one that speaks only of the remedy's reasons, effect or a payment ("…, ist dieser … zu begründen", "…, hat
#: dieser keine aufschiebende Wirkung; … zu zahlen", "… ergänzt werden").
_NOT_LODGED_MAIN = re.compile(
    r"begründ|aufschiebend|ergänz|zahl|überweis|bearbeit|entschieden|nachweis|unterlagen", re.IGNORECASE
)


def _refers_back(text: str) -> bool:
    """The main clause after a condition on the remedy is the notice itself ("Wenn Sie Widerspruch einlegen, muss
    dieser … eingehen") — unless it speaks only of the remedy's reasons, effect or a payment."""
    match = _REFERS_BACK.search(text)
    if match is None:
        return False
    main = re.split(r"[.;]", text[match.end() :], maxsplit=1)[0]
    return bool(_LODGED_MAIN.search(main)) or not _NOT_LODGED_MAIN.search(main)


#: A line that goes on with the sentence of the line before ("vom 01.10.2026 können Sie …", "eines Monats …").
_CONTINUED = re.compile(r"\s*(?:vom\b|\d|[a-zäöüß])")
#: A notice's heading ("Rechtsbehelfsbelehrung", "Rechtsmittelbelehrung:"): never inside the notice's sentence.
_NOTICE_HEADING = re.compile(
    r"^\s*(?:rechtsbehelfs?belehrung|rechtsmittelbelehrung|belehrung\s+über\s+(?:den|die)\s+rechts\w+)\b",
    re.IGNORECASE,
)


#: A line whose sentence runs on into the next ("… erhalten Sie eine" / "Rechtsbehelfsbelehrung"): an article or an
#: attribute at its end.
_RUNS_ON = re.compile(
    r"\b(?:eine[nmrs]?|keine[nmrs]?|die|der|den|dem|des|das|ihre[nmrs]?|unsere[nmrs]?|beigefügte[nmr]?|beiliegende[nmr]?|"
    r"enthaltene[nmr]?|anliegende[nmr]?|folgende[nmr]?|nachstehende[nmr]?|dortige[nmr]?|jeweilige[nmr]?|gesonderte[nmr]?)\s*$",
    re.IGNORECASE,
)


def _from_heading(text: str) -> str:
    """``text`` from the last notice heading before a remedy word on: what stands above it (a list's items, a
    hint, without a full stop) is no part of the notice. Unchanged without such a heading."""
    lines = text.split("\n")
    heads = [
        index
        for index, line in enumerate(lines)
        if _NOTICE_HEADING.match(line)
        and not (index and _RUNS_ON.search(lines[index - 1]))
        and any(_REMEDY.search(rest) for rest in lines[index:])
    ]
    return "\n".join(lines[heads[-1] :]) if heads else text


#: Where a clause of the notice starts ("…, vielmehr kann … Klage …").
_CLAUSE = re.compile(
    r"[,;]\s+(?=(?:vielmehr|jedoch|aber|sie|gegen|stattdessen|ein|der|die)\b)", re.IGNORECASE
)
#: The sentence after a notice without a period of its own speaks of the remedy's period when it says so.
_LIVE_FOLD = re.compile(
    r"frist|bekanntgabe|bekannt\s*gegeben|zustell|zugang|zugegangen|beginnt|einzulegen|zu\s+erheben|einzureichen",
    re.IGNORECASE,
)
#: A sentence that offers the remedy ("Sie können … Widerspruch einlegen", "legen Sie bitte Widerspruch ein"), and a
#: next sentence that counts from receiving the letter ("…nach Erhalt dieses Briefes", "nachdem Sie ihn bekommen haben").
_OFFER = re.compile(
    r"\b(?:können|kann)\s+(?:\w+\s+){0,6}?(?:widerspruch|einspruch|klage)\w*\s+(?:\w+\s+){0,2}?(?:einlegen|erheben|einreichen)\b"
    r"|\blegen\s+sie\s+(?:\w+\s+){0,3}?(?:widerspruch|einspruch)\s+ein\b",
    re.IGNORECASE,
)
_RECEIPT = re.compile(
    r"\berhalt\b|\b(?:erhalten|bekommen)\s+haben\b|\bzugang\b|\beingang\b|\bempfang\b", re.IGNORECASE
)
#: The next sentence refers back to the remedy offered ("Das müssen Sie …", "Dafür haben Sie einen Monat Zeit …").
_BACK_TO_OFFER = re.compile(
    r"^\W*(?:das|dies|dafür|dazu|hierfür|hierzu|sie\s+haben\s+dafür|sie\s+haben\s+hierfür)\b", re.IGNORECASE
)
_CONTRADICTORY = re.compile(r"widersprüchlich\w*", re.IGNORECASE)
_UNIT_WORD = r"(?:tag|tage|tagen|tages|woche|wochen|monat|monate|monaten|monats|jahr|jahre|jahren|jahres|days?|weeks?|months?|years?)"
#: A period counted back from an event: its unit followed by "vor", "bevor", "vorher", "zuvor", "before",
#: "prior to" or "in advance" — not with a start between ("nach Zustellung vor dem Sozialgericht", "of service
#: before the authority"), nor "vor dem …gericht" / "before the … court" (where the remedy is lodged).
_BACKWARD = re.compile(
    rf"\b{_UNIT_WORD}\b[\s,]*"
    r"(?:(?!klage|widerspr|einspr|nach\b|ab\b|seit\b|of\b|after\b|from\b|following\b)[^\W\d_]+[\s,]+){0,2}?"
    r"(?:vor(?!\s+(?:dem|der|einem|einer)\s+(?:(?:örtlich|[^\W\d_]+(?:en|em|er|es))\s+){0,2}?\w*(?:gericht|behörde)"
    r"|\s+ort\b)|bevor|vorher|zuvor"
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
#: A period a payment verb governs within one clause, or across one inserted clause right before the verb ("auch bei
#: Einlegung eines Widerspruchs innerhalb von zwei Wochen … zu zahlen", "innerhalb von zwei Wochen, nachdem …, zu
#: zahlen", "zahlen Sie bitte innerhalb von zwei Wochen, auch wenn Sie Widerspruch einlegen"), with no remedy or
#: lodging word between: the payment's period, never the remedy's ("…einzulegen; der Betrag ist … zu zahlen" and
#: "…muss innerhalb eines Monats … vorliegen, die Gebühr ist dennoch fällig" keep theirs).
_NOT_PAID_WORD = (
    r"(?!widerspr(?!uchsbescheid)|einspr(?!uchsentscheidung)|klage|einleg|eingeleg|einzuleg|erheb|erhob|einreich"
    r"|eingereich|einzureich|eingeh|eingegangen|vorlieg|zugeh)"
)
_PAY_VERB = r"\b(?:zu\s+(?:zahlen|überweisen|entrichten|begleichen)|fällig|zahlbar|zahlen|überweisen|entrichten|begleichen)\b"
_PAID_PERIOD = re.compile(
    rf"(?:{_PERIOD_WORDS.pattern})(?:{_NOT_PAID_WORD}[^,;]){{0,90}}?"
    rf"(?:,(?:{_NOT_PAID_WORD}[^,;]){{1,90}}?,\s*)?{_PAY_VERB}"
    rf"|\b(?:zahlen|überweisen|begleichen|entrichten)\s+sie\b(?:{_NOT_PAID_WORD}[^,;]){{0,60}}?(?:{_PERIOD_WORDS.pattern})",
    re.IGNORECASE,
)


def _unpaid(sentence: str) -> str:
    """``sentence`` without the periods a payment verb governs (:data:`_PAID_PERIOD`), its line breaks kept."""
    return _PAID_PERIOD.sub(lambda match: "\n" * match.group().count("\n") or " ", sentence)


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
#: Service with a Postzustellungsurkunde (§ 3 VwZG with §§ 177–182 ZPO): the postman writes the day it was served on
#: the yellow envelope — handed over, put in the letterbox (§ 180 ZPO) or, deposited at the post office, the day the
#: notice of the deposit was left (§ 181 ZPO), never the day it was picked up.
_PZU = re.compile(r"(?:post)?zustellungsurkunde|\bpzu\b(?!\s*[-/.]?\s*\d)|(?-i:\bmit\s+ZU\b)", re.IGNORECASE)
#: A header cell naming another service or a copy, not this letter's on the person ("Original mit PZU an Ihren
#: Bevollmächtigten", "Abschrift", "nachrichtlich", "nicht mit PZU", "zugestellt am 03.09.2026", "Betreff: Ihre
#: Anfrage zur Zustellungsurkunde").
_NOT_THIS_SERVICE = re.compile(
    r"\b(?:vom|am|wurden?|worden|abschrift|zweitschrift|kopie\w*|nachrichtlich|kenntnis\w*|original\w*|bevollmächtigt\w*"
    r"|vertret\w*|rechtsanw\w*|anwalt\w*|nicht|kein\w*|ohne|betreff\w*|anfrage\w*)\b|\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}",
    re.IGNORECASE,
)
#: A sentence naming the service that says the letter is not served so, or sends a copy of another's certificate
#: ("nicht mit Postzustellungsurkunde, sondern …", "eine Kopie der Postzustellungsurkunde").
_NOT_SERVED = re.compile(r"\b(?:nicht|kein\w*|ohne|kopie\w*|abschrift\w*)\b", re.IGNORECASE)
#: A sentence naming this letter served so ("Dieser Bescheid wird Ihnen mit Postzustellungsurkunde zugestellt").
_SELF_SERVED = re.compile(
    r"\bdiese[nmrs]?\s+(?:\w+\s+){0,2}?\w*(?:bescheid|festsetzung|entscheidung|verfügung|schreiben|brief)\w*\b"
    r"[^.;]{0,80}?(?:(?:post)?zustellungsurkunde|\bpzu\b)",
    re.IGNORECASE,
)
#: A line of the header naming the service is short ("Mit Postzustellungsurkunde", "Zustellung gegen PZU").
_SERVICE_LINE_WORDS = 8
#: Provided for download (a portal or electronic mailbox): the day after the earliest download.
_PORTAL = re.compile(
    r"zum\s+(?:abruf|download)\s+bereit\w*|bürgerportal|nutzerkonto|elektronisch\w*\s+(?:post)?fach|online-?postfach",
    re.IGNORECASE,
)
#: "Musterstadt, 06.11.2026" / "Musterstadt, den 06.11.2026": a place and the letter's date.
_PLACE_DATE = re.compile(
    r"^[A-ZÄÖÜ][\w .\-/()]{1,40},\s*(?:(?i:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag)"
    r",?\s*)?(?:den\s+)?$"
)
#: "Datum 06.11.2026", "Bescheiddatum: …", "Erstellt am …", "Stand: …": a label of the letter's own date (only
#: :data:`_OWN_LABEL` is strong).
_DATE_LABEL = re.compile(
    r"(?:^|[\s·|])(?:\w*datum|datum\s+(?:des|der)\s+\w+|date|(?:erstellt|ausgestellt)\s+am|stand)\s*:?\s*$",
    re.IGNORECASE,
)
#: A label of the place and date before them on one line ("Ort, Datum: Beispielhausen, 06.11.2026").
_PLACE_LABEL = re.compile(r"^(?:ort|datum)\s*(?:,|/|und)\s*(?:datum|ort)\s*:\s*", re.IGNORECASE)
#: An empty field's label in a column before the date's own ("Ihr Zeichen:   Beispielhausen, 06.11.2026").
_EMPTY_LABEL = re.compile(r"[A-ZÄÖÜa-zäöüß][\w .\-/]{0,30}:")
#: A cell of a table row that holds an amount ("85,00 EUR"): a row of payments, no reference line.
_AMOUNT_CELL = re.compile(r"\d,\d{2}\b|\b(?:eur|euro)\b|€", re.IGNORECASE)
#: A label of a table's money or cut-off column ("Betrag", "Summe", "Saldo"): a payments table, no reference line.
_MONEY_LABEL = re.compile(r"betrag|summe|saldo", re.IGNORECASE)
#: A town after a postcode ("12345 Beispielhausen", "60311 Frankfurt am Main"): where the letter's own place and date
#: may name.
_POSTCODE_TOWN = re.compile(
    # within its line and column: one space between the town's words, never a line break ("13341 Berlin" over "Frau
    # Mara Probe" is "Berlin") nor the text layer's column gap
    r"\b\d{5}[^\S\n]+([A-ZÄÖÜ][\w.\-()/]*(?: (?:am|an der|im|in der|ob der|[A-ZÄÖÜ(][\w.\-()/]*)){0,3})"
)
#: The first words of a town's name that alone name no town ("Bad Homburg", "St. Ingbert", "Sankt Augustin").
_TOWN_PREFIX = frozenset({"bad", "st.", "sankt"})
#: What follows a town's first word in its short or district form: "-Höchst", "/M.", " (Saale)", " a. M.", " i. Br.",
#: " a. d. Ruhr", " v. d. Höhe", " am Main", " OT Golm" — never another word ("Frankfurt Hauptwache").
_TOWN_QUALIFIER = re.compile(r"-|/| \(| (?:[a-z]\.|am |an |im |in |ob |ot )")
#: A time of day under a date ("09:00 Uhr, Raum 2.14"): an appointment's, not the letter's.
_TIME_BELOW = re.compile(r"\b\d{1,2}[:.]\d{2}\s*(?:uhr|h)\b|\buhr\b", re.IGNORECASE)
#: A line of opening hours under the date line ("Sprechzeiten: Mo–Fr 08:00–12:00 Uhr", "Telefon … (Mo–Fr 8–12 Uhr)"):
#: it says so, or runs from one weekday to another — never an appointment's ("Termin", "Einladung", "Raum", "Zimmer").
_HOURS = re.compile(
    r"sprechzeit|öffnungszeit|servicezeit|geschäftszeit|erreichbar"
    r"|\b(?:mo|di|mi|do|fr|sa|montags?|dienstags?|mittwochs?|donnerstags?|freitags?|samstags?)\.?\s*(?:-|–|bis)\s*"
    r"(?:di|mi|do|fr|sa|so|dienstags?|mittwochs?|donnerstags?|freitags?|samstags?|sonntags?)\b",
    re.IGNORECASE,
)
_NOT_HOURS = re.compile(r"termin|einladung|\braum\b|\bzimmer\b", re.IGNORECASE)
#: A line that labels the date under or after it as another one ("Antrag vom", "geboren am").
_ANOTHER = re.compile(r"\b(?:vom|seit|bis|ab|am|zum|antrag\w*|geboren|geburtsdatum)\s*:?\s*$", re.IGNORECASE)
#: Words of a date that is not the letter's: a due day, a validity, an appointment, a weekday before it.
_OTHER_DATE = re.compile(
    r"\b(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag|monday|tuesday|wednesday"
    r"|thursday|friday|saturday|sunday|valid\w*|until|due|bis|ab|am|zum|vom|seit)\b|fällig|zahlung|zahlbar|"
    # "Leistungsabteilung", "Leistungsstelle" are a department's name, not a benefit's date
    r"gültig|termin|anhörung|beginn|geburt|ablauf|liefer|leistung(?!s?(?:abteilung|stelle|bereich|team))|zeitraum"
    r"|frist|eingang|antrag|stichtag|\bende\b",
    re.IGNORECASE,
)
_CREATED_ON = re.compile(r"(?:erstellt|ausgestellt)\s+am", re.IGNORECASE)
#: "Stand: …" as the label: an account's or a table's as-of date in the body ("Forderungsaufstellung, Stand: …"); the
#: letter's own (weak) only in its header or on its date line.
_AS_OF = re.compile(r"(?:^|[\s·|,])stand\s*:?\s*$", re.IGNORECASE)
#: A label that names the letter's own date; any other "…datum" may be another's ("Einzugsdatum").
_OWN_LABEL = re.compile(
    r"(?:(?:^|[\s·|])(?:(?:bescheid|brief|ausstellungs|erstellungs|bearbeitungs)?datum"
    r"|datum\s+(?:des|der)\s+(?:bescheid\w*|schreiben\w*|brief\w*)|(?:erstellt|ausgestellt)\s+am)"
    r"|(?:^|[·|]\s*|\s{2,})date)\s*:?\s*$",  # "Date:" only as the whole label, never "Effective date:"
    re.IGNORECASE,
)
#: The DIN 5008 reference line's labels, ending in "Datum" ("Ihr Zeichen  Unser Zeichen  Datum").
_REFERENCE_LABELS = re.compile(
    r"(?:^|\s)(?:(?:bescheid|brief|ausstellungs|erstellungs|bearbeitungs)?datum"
    r"|datum\s+(?:des|der)\s+(?:bescheid\w*|schreiben\w*|brief\w*))\s*:?$",
    re.IGNORECASE,
)
#: A reference line's "Datum" column anywhere in its labels ("Unser Zeichen   Datum   Telefon").
_DATUM_COLUMN = re.compile(r"(?:^|\s)datum(?=\s|$)(?!\s+(?:des|der|von)\b)", re.IGNORECASE)
#: The recipient's postcode and town, the last line of the address block (DIN 5008: the date line follows it).
_POSTCODE_LINE = re.compile(r"^(?:D-?\s?)?\d{5}\s[A-ZÄÖÜ][\w.\-()/]*(?:\s[\w.\-()/]+){0,4}$")
#: The line above the postcode holds a number (a house number, a Postfach): an address, not a heading.
_STREET_LINE = re.compile(r"\d")
#: A street named after a place ("Am Mühlbach 3", "Zum Sportplatz 1", "An der Kirche 2"): no appointment's "am".
_STREET_PREFIX = re.compile(
    r"^(?:Am|An\s+der|An\s+den|Im|In\s+der|Zum|Zur|Auf\s+der|Auf\s+dem|Unter\s+den|Vor\s+dem|Hinter\s+der)\s+(?=[A-ZÄÖÜ])"
)
#: A town's name after a river or region ("Frankfurt am Main", "Mülheim an der Ruhr"): no weekday, no due word.
_TOWN = re.compile(
    r"\b(?:am|an\s+der|ob\s+der|im|in\s+der)\s+"
    r"(?!(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonnabend|Sonntag)\b)[A-ZÄÖÜ][a-zäöüß]+"
)
#: Where the address field starts its last line: the recipient's postcode and town, also when the text layer runs
#: the info block beside it into the same line ("12345 Beispielhausen   Telefon   0123 456-0").
_POSTCODE_START = re.compile(r"^(?:D-?\s?)?\d{5}\s[A-ZÄÖÜ]")
#: The text layer's column gap (:mod:`ordnung.ingest.text`): what stands before it is another column's.
_COLUMN = "   "
#: How many lines of the info block may stand under the recipient's postcode line (Telefon, E-Mail, Datum …).
_INFO_TAIL = 8


#: A title's, a department's or a town's abbreviation before a capital ("Dr. Max Probe", "Abt. Steuern",
#: "66386 St. Ingbert", "Sprechzeiten: Mo. Di. Do."): its period ends no sentence, so it never ends the header.
_ABBREVIATION = re.compile(
    r"\b(Dr|Prof|Dipl|Ing|St|Abt|Mo|Di|Mi|Do|Fr|Sa|So|Nr|Zi|Hd|Fa|Spk|Bez)\.(?=\s+[A-ZÄÖÜ])"
)


def _unabbreviated(lines: list[str]) -> list[str]:
    """The lines without the periods of :data:`_ABBREVIATION` (to find where a header ends)."""
    return [_ABBREVIATION.sub(r"\1", line) for line in lines]


def _address_field_end(lines: list[str], rows: int) -> int:
    """Where the address field and the info block printed beside it end on a letter without a salutation: the
    first blank line after the last postcode line before the letter's first sentence (a street or Postfach line
    above it; at most :data:`_INFO_TAIL` lines on), never past that sentence or a notice's line — so an info block
    whose label and value stand in columns ("Datum   06.11.2026"), run into the address's lines by the text
    layer, is no table that ends the header (nor is a "Widerspruchsstelle" in the letterhead the notice).
    ``rows`` otherwise."""
    post: int | None = None
    end = rows
    for index, line in enumerate(lines):
        stripped = line.strip()
        if (
            _SALUTATION.match(stripped)
            or _SENTENCE_END.search(line)
            or (stripped.endswith(".") and len(stripped.split()) >= 4)
            # a notice's line ("Widerspruchsstelle" alone is none)
            or (_GERMAN_REMEDY.search(stripped) and _PERIOD_WORDS.search(stripped))
        ):
            return end if post is None or end > post else max(end, index)
        previous = next((lines[at].strip() for at in range(index - 1, -1, -1) if lines[at].strip()), "")
        if _POSTCODE_START.match(stripped) and re.search(r"\d", previous):
            post = index
        elif post is not None and end <= post and (not stripped or index - post > _INFO_TAIL):
            end = max(end, index)
    return end if post is None or end > post else max(end, len(lines))


def _beside_address(before: str) -> bool:
    """The column right before a date that stands alone in its own is an address line (a house number, a
    postcode, a Postfach) — no label of it ("Fälligkeit", "Antrag vom", "Termin:")."""
    column = before.rstrip().rsplit(_COLUMN, 1)[-1].strip()
    words = column.split()
    return bool(
        words
        and re.search(r"\d", column)
        and not column.endswith(":")
        and not _OTHER_DATE.search(words[-1])
        and not _ANOTHER.search(column)
    )


#: A street name in an address line the text layer ran into the date's line ("Am Lindenhof 2", "Zum Wald 3"), and a
#: hyphenated name ("Freiherr-vom-Stein-Str. 2"): their "Am", "Zum", "vom" are no appointment's or due day's.
_STREET_NAME = re.compile(
    r"\b(?:Am|Zum|Zur|Vom|Im|An\s+der|An\s+den|In\s+der|Auf\s+dem|Auf\s+der)\s+[A-ZÄÖÜ][\w.\-]*"
    r"(?:\s+[A-ZÄÖÜ][\w.\-]*){0,2}\s+\d+\s?[a-zA-Z]?\b|\b[A-ZÄÖÜ][\w.]*(?:-[\w.]+)+\s+\d+\s?[a-zA-Z]?\b"
)


def _unaddressed(before: str) -> str:
    """The words before a date without the street names in the columns before its own: an address line the
    text layer ran into its line ("Am Lindenhof 2   Datum …"), never its own column's words ("Am Markt 3, …")."""
    head, gap, own = before.rstrip().rpartition(_COLUMN)
    if not gap:
        return before
    return _STREET_NAME.sub(" ", head) + gap + own + before[len(before.rstrip()) :]


def _own_column(before: str) -> str | None:
    """The date's own column (after the text layer's last column gap) when the column before it is an address
    line (a house number, a postcode, a Postfach: :func:`_beside_address`) or the columns before it are only empty
    fields' labels ("Ihr Zeichen:", "Ihre Nachricht vom:" — never another date's, "Termin:") — ``None``
    otherwise."""
    if _COLUMN not in before.rstrip():
        return None
    left, own = before.rstrip().rsplit(_COLUMN, 1)
    cells = [cell.strip() for cell in left.split(_COLUMN) if cell.strip()]
    labels = bool(cells) and all(_EMPTY_LABEL.fullmatch(cell) for cell in cells)
    if not (labels or _beside_address(left + _COLUMN)) or _OTHER_DATE.search(
        _TOWN.sub(" ", _STREET_NAME.sub(" ", left))
    ):
        return None
    if labels and _ANOTHER.search(left):
        return None
    return own.lstrip() + before[len(before.rstrip()) :]


def _towns(text: str) -> set[str]:
    """The towns the page names after a postcode (the sender's, the recipient's), folded for comparing."""
    return {" ".join(match.group(1).split()).casefold() for match in _POSTCODE_TOWN.finditer(text)}


def _town_head(town: str) -> str | None:
    """A town's first word (two after "Bad", "St.", "Sankt") when its name has more ("Frankfurt am Main",
    "Frankfurt/Main", "Halle (Saale)"): ``None`` otherwise."""
    words = re.split(r"[ /]", town)
    size = 2 if words[0] in _TOWN_PREFIX else 1
    return " ".join(words[:size]) if len(words) > size else None


def _names_town(place: str, towns: set[str], above: str, *, beside_address: bool) -> bool:
    """A place and date's place is a town the page names after a postcode on its line ("Beispielhausen", "Frankfurt"
    for "Frankfurt am Main", "Berlin-Mitte" for "Berlin", "Frankfurt a. M." or "Frankfurt/M." for "Frankfurt am
    Main", "Halle (Saale)" for "Halle/Saale", umlauts spelled out: "Muenchen" for "München") or in a line above it
    (the letterhead's "Landkreis Beispielhausen") — never another word after the town ("Frankfurt Hauptwache"), no
    "Abholung am Schalter", "Sprechtag" or "Zustellung   Beispielhausen". On a line of the
    address field the text layer ran the info block into (``beside_address``: "Probeweg 2   Beispielhausen, …",
    "Mara Probe   Beispielhausen, …") only the date's own column is the place."""
    head = place.split(",")[0]
    name = _fold_town(" ".join((head.rsplit(_COLUMN, 1)[-1] if beside_address else head).split()))
    if not name:
        return False
    if any(
        name == town
        or town.startswith(f"{name} ")
        # the town with its district or river: "Berlin-Mitte" for "Berlin", "Frankfurt am Main" for "Frankfurt" —
        # never another word after it ("Frankfurt Hauptwache")
        or (name.startswith(town) and bool(_TOWN_QUALIFIER.match(name, len(town))))
        # the same town shortened or with its district: "Frankfurt a. M.", "Frankfurt/M.", "Frankfurt-Höchst" for
        # "Frankfurt am Main" or "Frankfurt/Main", "Freiburg i. Br." for "Freiburg im Breisgau"
        or (
            (short := _town_head(town)) is not None
            and (name == short or (name.startswith(short) and bool(_TOWN_QUALIFIER.match(name, len(short)))))
        )
        for town in map(_fold_town, towns)
    ):
        return True
    return bool(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", _fold_town(" ".join(above.split()))))


def _fold_town(text: str) -> str:
    """A town's name as compared: case and umlauts folded ("Muenchen" is "München", "STRASSE" is "Straße")."""
    folded = text.casefold()
    for umlaut, spelled in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        folded = folded.replace(umlaut, spelled)
    return folded


_DECISION = (
    r"(?:bescheid\w*|festsetzung\w*|entscheidung\w*|verfügung\w*|beschluss\w*|urteil\w*|verwaltungsakt\w*)"
)
#: A word that dates something other than the decision when it stands right before "vom".
_NOT_ISSUER = r"(?:\w*zeit\w*|antrag\w*|schreiben\w*|nachricht\w*|anhörung\w*|mitteilung\w*|widerspruch\w*|einspruch\w*)"
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
#: A decision on a remedy: its notice's "Bescheid vom …" is the decision it reshapes, not this letter.
_ON_REMEDY = re.compile(r"widerspruchsbescheid\w*|einspruchsentscheidung\w*", re.IGNORECASE)
#: A date that starts a range ("vom 01.12.2026 bis 31.05.2027", "01.12.2026 - 31.05.2027"): a period's start.
_RANGE = re.compile(r"\s*(?:bis\b|-\s*\d)", re.IGNORECASE)
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
    #: It names another decision by a compound noun or a back-reference ("Gegen den Steuerbescheid …", no "dies-", no
    #: date) whose date the letter never gives: a cover letter or reminder may restate that decision's notice.
    restates: bool = False
    #: It names another decision ("Gegen den Gebührenbescheid …", "Hiergegen …" on a letter that never names itself
    #: one) whose date the letter gives ("mit Gebührenbescheid vom 27.10.2026"): its period may run from that one.
    another_dated: bool = False

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
    word = re.sub(r"^(?:anfechtungs|verpflichtungs)", "", found.group().casefold()) if found else ""
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


#: A remedy already lodged, reported in the past ("…, da er nicht innerhalb eines Monats … erhoben wurde", "insbesondere
#: wurde er fristgerecht … eingelegt", "ist … erhoben worden") — never a requirement ("… eingelegt worden sein").
_REPORTED = re.compile(
    r"\b(?:eingelegt|erhoben|eingereicht)\s+(?:wurden?|worden\s+(?:ist|sind|war|waren))\b"
    r"|\bwurden?\s+(?:\w+\s+){0,10}?(?:eingelegt|erhoben|eingereicht)\b(?!\s+werden)"
    r"|\b(?:ist|sind|war|waren)\s+(?:\w+\s+){0,10}?(?:eingelegt|erhoben|eingereicht)\s+worden\b(?!\s+sein)",
    re.IGNORECASE,
)
#: A condition around a remedy in the perfect or past — a notice, never a report ("…, wenn nicht innerhalb von zwei
#: Wochen … Einspruch eingelegt worden ist", "Ist … kein Widerspruch erhoben worden, …", "Die Frist ist auch gewahrt,
#: wenn …").
_CONDITIONAL = re.compile(
    r"\b(?:wenn|falls|sofern|soweit|sobald)\b|^\s*(?:ist|sind|war|waren|wurde|wurden)\b"
    r"|\bkein(?:en)?\s+(?:widerspruch|einspruch|klage)",
    re.IGNORECASE,
)
#: A sentence that offers the remedy all the same ("… kann … Klage erhoben werden", "… ist … einzulegen", "Die Klage
#: muss … erhoben werden").
_OFFERED = re.compile(
    r"\b(?:kann|können|muss|müssen)\b[^.;]{0,160}?\b(?:(?:erhoben|eingelegt|eingereicht)\s+werden|einlegen|erheben"
    r"|einreichen)\b"
    r"|\b(?:einzulegen|zu\s+erheben|einzureichen)\b|\b(?:legen|erheben|reichen)\s+sie\b",
    re.IGNORECASE,
)
#: A notice that refers back to a decision named before it ("Hiergegen kann …", "Sie können dagegen …"): on a letter
#: that never names itself a decision (a reminder, a cover letter), another decision (security V4-2, round 4).
_BACK_REFERENCE = re.compile(r"\b(?:hiergegen|dagegen)\b", re.IGNORECASE)
#: A decision named by its article alone ("Bekanntgabe des Bescheides", "gegen den Bescheid"): beside a notice naming
#: "diesen Bescheid", the same decision — never a compound noun ("des Steuerbescheides") or a back-reference ("o. g.").
_BARE_DECISION = re.compile(
    r"\b(?:gegen\s+(?:den|die|das)|(?:bekanntgabe|zustellung)\s+(?:des|der))\s+"
    r"(?:bescheid(?:e?s)?|festsetzung|entscheidung|verfügung)\b",
    re.IGNORECASE,
)
#: A sentence naming this letter a decision ("Gegen diesen Bescheid ist der Widerspruch gegeben."), with a remedy.
_THIS_DECISION = re.compile(
    r"\bdiese[nmrs]?\s+(?:\w+\s+){0,2}?\w*(?:bescheid|festsetzung|entscheidung|verfügung)", re.IGNORECASE
)


def _names_this_decision(pages: Sequence[PageInput]) -> bool:
    """A sentence of the letter names this letter a decision and a remedy against it, not ruled out ("Gegen diesen
    Bescheid ist der Widerspruch gegeben."): a notice's bare "des Bescheides" is then this one (false positives
    R4FP-6, round 4)."""
    return any(
        _THIS_DECISION.search(sentence) and _GERMAN_REMEDY.search(sentence) and not _NEGATED.search(sentence)
        for page in pages
        for sentence in sentences(join_hyphenated(_visible(page)))
    )


def _elsewhere(
    text: str,
    pages: Sequence[PageInput],
    own: str | None = None,
    *,
    back: bool = False,
    this_decision: bool = False,
) -> tuple[date, ...]:
    """For a notice about another decision named without a date of its own ("Gegen den Gebührenbescheid kann
    …", or ``back``: "Hiergegen kann …" on a letter that never names itself a decision), the dates the letter's
    visible text gives a decision ("mit Gebührenbescheid vom 03.09.2026"): its period may run from then, so they
    count as the letter's own (they only ever make the start earlier, or none). None when the notice names the
    decision by its article alone ("nach Bekanntgabe des Bescheides") on a letter whose notice names "diesen
    Bescheid" (``this_decision``): that is this letter."""
    # a closing line folded into the notice ("Dieses Schreiben wurde maschinell …") is no part of it
    scope = text if own is None else own
    named = [match.group() for match in _ANOTHER_DECISION.finditer(text)]
    if not (named or back) or _SELF.search(scope) or date_spans(fold_punctuation(scope)):
        return ()
    if this_decision and not back and all(_BARE_DECISION.match(name) for name in named):
        return ()
    days: list[date] = []
    for page in pages:  # the page's words as one run: "mit Gebührenbescheid vom" / "03.09.2026 …" wrapped
        run = _flat(join_hyphenated(_visible(page)))
        days += _issued(run, (_ISSUED,)) + _issued(run, (_DECISION_DATED,))
        if back:
            # "Hiergegen …": never the hearing before the decision ("Mit Schreiben vom 15.08.2026 haben wir Sie
            # angehört"), a decision that doesn't name itself one being this letter (false alarms FA-5)
            days += [
                day
                for sentence in sentences(join_hyphenated(_visible(page)))
                if not _HEARING.search(sentence)
                for day in _issued(_flat(sentence), (_LETTER_ISSUED,))
            ]
        else:
            days += _issued(run, (_LETTER_ISSUED,))
    return tuple(dict.fromkeys(days))


#: A hearing before a decision ("haben wir Sie angehört", "Anhörung", "Gelegenheit zur Stellungnahme").
_HEARING = re.compile(r"anhör|angehört|gelegenheit\s+zur\s+(?:stellungnahme|äußerung)", re.IGNORECASE)


#: Other ways a letter dates a decision it names: "Bescheiddatum: …", "…bescheid 2025, datiert auf den …".
_DECISION_DATED = re.compile(
    rf"\bbescheiddatum\w*(?:\s+\S+){{0,3}}?\s*:?\s*$|{_DECISION}(?:\s+[^\s;:]+){{0,4}}?\s+datiert\s+(?:auf\s+den|vom|am)\s*$",
    re.IGNORECASE,
)


#: A decision's noun right before "vom" ("Bescheid vom", "Festsetzung vom"): the decision's date for certain.
_ISSUED_RIGHT = re.compile(rf"{_DECISION}\s+vom\s*$", re.IGNORECASE)


def _named(text: str) -> tuple[tuple[date, ...], tuple[date, ...]]:
    """The dates of the decisions the notice names (:func:`_issued`), split: right after a decision's noun and
    starting no range ("Gegen den Bescheid vom 01.10.2026"; strong), or with words between ("Bescheid über
    Leistungen vom 01.12.2026 an", "für die Zeit vom … bis …"; weak — a period's start, perhaps)."""
    folded = fold_punctuation(text)
    right = tuple(
        day
        for start, end, mention in date_spans(folded)
        if not mention.ambiguous
        and (day := mention.as_date()) is not None
        and _ISSUED_RIGHT.search(folded[:start])
        and not _RANGE.match(folded[end:])
    )
    named = _issued(text)
    return tuple(day for day in named if day in right), tuple(day for day in named if day not in right)


def remedy_notices(pages: Sequence[PageInput]) -> list[RemedyNotice]:
    """Every sentence of the visible text naming a remedy (Widerspruch, Einspruch, Klage, objection, appeal)
    with a period in it or in the sentence after it — that one only when it names neither a remedy nor a
    payment. Words split across lines are joined as quotes are matched ("Wider-\\nspruch"); "Monatsfrist" is
    one month. A notice whose period can't be read, or counts back from an event without a start from this
    letter, is kept but can't be dated (:attr:`RemedyNotice.datable`). On a decision on a remedy, a sentence
    reporting a remedy already lodged, without offering one ("…, da er nicht innerhalb eines Monats … erhoben
    wurde": a Widerspruchsbescheid's reasoning), is none — never a condition ("…, wenn nicht … Einspruch eingelegt
    worden ist", :data:`_CONDITIONAL`); on any other letter such a sentence stays a notice."""
    found: list[RemedyNotice] = []
    # "Hiergegen …" on a letter that never names itself a decision refers to another; "des Bescheides" beside a
    # notice naming "diesen Bescheid" is this one (security V4-2, false positives R4FP-6, round 4)
    names_itself = bool(_NAMES_ITSELF.search("\n".join(_visible(page) for page in pages)))
    this_decision = _names_this_decision(pages)
    # only a decision on a remedy (a Widerspruchsbescheid) reports one already lodged in its reasoning
    self_decided = bool(_SELF_DECIDED.search("\n".join(_visible(page) for page in pages)))
    for page in pages:
        folded = sentences(join_hyphenated(_visible(page)))
        for index, sentence in enumerate(folded):
            if not _REMEDY.search(sentence) or (_PAYS.search(sentence) and not _LODGES.search(sentence)):
                continue
            if (
                self_decided
                and _REPORTED.search(sentence)
                and not _OFFERED.search(sentence)
                and not _CONDITIONAL.search(sentence)
            ):
                continue  # the remedy already lodged, reported (false positives R4FP-8, round 4)
            following = folded[index + 1] if index + 1 < len(folded) else ""
            own = _periods(_unpaid(sentence))
            # a sentence after a notice with its own period that counts back ("einige Tage vor Fristablauf
            # absenden"): a tip, never folded into it
            foldable = (
                bool(following)
                and not _REMEDY.search(following)
                and not _PAYMENT.search(following)
                and not (own.found and _BACKWARD.search(following) and not _FORWARD.search(following))
            )
            after = _periods(following) if foldable else _Periods((), False)
            if not own.found and not after.found:
                continue
            text = f"{sentence} {following}" if foldable else sentence
            # the sentence after counts for the date whenever it may go on about the period (the shorter wins),
            # but for the check to fire only when the notice has no period of its own and it names its start
            alone = _from_heading(sentence if own.found else text)
            mine = _periods(_from_heading(_unpaid(sentence)))
            backward = bool(_BACKWARD.search(text)) and not _FORWARD.search(text)
            handled = _HANDLED.search(alone) and not _FORWARD.search(alone) and not _LODGED.search(alone)
            quote = _window(text)
            scope = sentence if own.found else text
            back = not names_itself and bool(_BACK_REFERENCE.search(scope))
            elsewhere = _elsewhere(text, pages, scope, back=back, this_decision=this_decision)
            another = (
                (bool(_AGAINST_NAMED.search(scope)) or back)
                and not _SELF.search(scope)
                and not date_spans(fold_punctuation(scope))
            )
            found.append(
                RemedyNotice(
                    quote=quote if quote is not None else _flat(sentence)[:QUOTE_CAP],
                    text=_flat(text),
                    periods=(*own.good, *after.good),
                    notified=bool(_NOTIFIED.search(text)) and not _ARRIVAL.search(text),
                    remedy=_remedy(sentence),
                    live=bool(_REMEDY.search(_CONTRADICTORY.sub(" ", sentence)))
                    and not _NOT_LIVE.search(alone)
                    and not _debit_right(alone)
                    and not (_TAKEN_AS_LODGED.search(alone) and not _refers_back(alone))
                    and not (_OTHER_START.search(alone) and not _FORWARD.search(alone))
                    and not handled  # the person's own objection being dealt with
                    and not (_REASONS_ONLY.search(alone) and not _LODGES.search(alone))
                    and not _NEGATED.search(
                        _negation_scope(_from_heading(sentence), _from_heading(text), own.found)
                    )
                    and not backward  # counted back from an event (a hearing): no deadline from this letter
                    and (
                        own.found
                        or bool(_LIVE_FOLD.search(following))
                        or bool(
                            _OFFER.search(sentence)
                            and _BACK_TO_OFFER.search(following)
                            and _RECEIPT.search(following)
                        )
                    ),
                    # counted back from an event: never dated forward, whatever start words it also has
                    datable=not (own.odd or (not own.found and after.odd))
                    and not _BACKWARD.search(text)
                    and quote is not None,
                    issued=_named(text)[0],
                    grounding=_grounding(page),
                    # its own lines' periods below its heading; else (none there, or no heading) the sentence's
                    stated=mine.good if mine.found else (own.good if own.found else after.good),
                    mentioned=(
                        *_issued(_own_lines(text), (_LETTER_ISSUED,)),
                        *_named(text)[1],
                        *elsewhere,
                    ),
                    restates=another and not elsewhere,
                    another_dated=another and bool(elsewhere),
                )
            )
    return found


def formally_served(pages: Sequence[PageInput], notices: Sequence[RemedyNotice] | None = None) -> bool:
    """Whether the letter says it is served on the person with a Postzustellungsurkunde (the yellow envelope):
    a short line of its first page's header ("Mit Postzustellungsurkunde", "Zustellung gegen PZU"), or a sentence
    naming this letter so ("Dieser Bescheid wird Ihnen mit Postzustellungsurkunde zugestellt") — never another
    decision's service ("Der Bescheid vom … wurde Ihnen … zugestellt"), a line in its body or a tip on how to
    send an objection, a copy or a representative's ("Abschrift", "Original mit PZU an Ihren Bevollmächtigten"), a
    negation ("nicht mit Postzustellungsurkunde") or a reference number ("PZU-2026-0815") — and every remedy notice it
    gives counts from notification or service (a notice naming no start, or counting from the letter's own date,
    keeps the letter unmarked), none from another decision the letter dates (:func:`_runs_from_another_decision`).

    Then the date the postman wrote on the envelope is the day it was served (§ 3 VwZG with §§ 180, 181 ZPO, and
    its notification, § 41 Abs. 5 VwVfG): the app asks for that date (the receipt cites ``pzu``,
    :attr:`~ordnung.rules.RuleContext.formal_service`), and a notice's period starts on it
    (:func:`envelope_start`)."""
    if not pages:
        return False
    lines = fold_punctuation(join_hyphenated(_visible(pages[0]))).splitlines()
    rows = len(header(_unabbreviated(lines)))
    in_header = any(
        _PZU.search(cell)
        and len(cell.split()) <= _SERVICE_LINE_WORDS
        and not cell.rstrip().endswith(".")
        and not _NOT_THIS_SERVICE.search(cell)
        for line in lines[:rows]
        for cell in line.split(_COLUMN)
    )
    named = any(
        not _NOT_SERVED.search(found.group())
        for page in pages
        for found in _SELF_SERVED.finditer(_flat(_visible(page)))
    )
    if not (in_header or named):
        return False
    notices = remedy_notices(pages) if notices is None else notices
    # a notice of another decision the letter dates ("Hiergegen …" in a reminder naming "Gebührenbescheid vom …", "Gegen
    # den Bescheid vom …" before this letter's date): its period runs from that decision's notification, never from
    # this envelope — but a notice naming this letter too ("… in Gestalt dieses Widerspruchsbescheides", "und diesen
    # Widerspruchsbescheid") or a decision on a remedy counts from this one's service (§ 74 VwGO)
    own = {statement.letter_date for statement in letter_statements(pages[:1]) if statement.letter_date}
    own |= {dated.day for dated in _header_dates(pages[0]) if dated.own}
    if any(_runs_from_another_decision(notice, min(own) if own else None) for notice in notices):
        return False
    return all(_NOTIFIED.search(notice.text) or _ARRIVAL.search(notice.text) for notice in notices)


def _runs_from_another_decision(notice: RemedyNotice, own: date | None) -> bool:
    """A notice whose period runs from another decision's notification the letter dates (:func:`formally_served`):
    "Hiergegen …" on a reminder naming "Gebührenbescheid vom 27.10.2026" (:attr:`RemedyNotice.another_dated`), or one
    naming a decision dated before the letter's own date ``own`` ("Gegen den Bescheid vom 27.10.2026 …") — never one
    naming this letter too or a decision on a remedy (a Widerspruchsbescheid's "Gegen den Bescheid vom 03.06.2026 in
    Gestalt dieses Widerspruchsbescheides …")."""
    if _SELF.search(notice.text) or _DECIDED_REMEDY.search(notice.text):
        return False
    return notice.another_dated or any(own is None or day < own for day in notice.issued)


def envelope_start(spec: DateSpec, ctx: RuleContext) -> date | None:
    """The date on the yellow envelope that starts a period counted from the letter's date without delivery days
    (``spec``: the check's to-do or the letter's own notice, :func:`notice_rival`) on a letter served with a
    Postzustellungsurkunde (``ctx.formal_service``): the arrival the person confirmed — asked for as the date on
    the envelope — when it is after the letter's date and within :data:`LETTER_DATE_SPAN` days of it (the earliest
    date the letter has for itself: a corrected one too). A later one is no envelope's date of this letter (a
    pickup weeks later, a planted service line on a plain letter): the letter's date is kept, the earlier."""
    if not ctx.formal_service or spec.type != "relative" or spec.delivery_rule != "none":
        return None
    start = _iso(spec.anchor_date) if spec.anchor == "explicit_date" else None
    arrival = ctx.received_date if ctx.received_confirmed else None
    if start is None or arrival is None:
        return None
    earliest = min(start, ctx.document_date) if ctx.document_date else start
    return arrival if start < arrival <= earliest + timedelta(days=LETTER_DATE_SPAN) else None


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
    sender = extraction.sender
    public = sender is not None and scope_for_party_kind(sender.kind, name=sender.name) is not None
    decision = public and bool(_AGAINST_DECISION.search(" ".join(text.split())))
    return (
        any(notice.live for notice in notices)
        and (shows_administrative_act(text) or decision or bool(_DECISION_HEADING.search(text)))
        and not _law_dated(extraction, notices, text)
    )


#: How the header names a date of the letter's: after a date label (``label``), under the reference line's
#: "Datum" column (``column``), after a place (``place``), alone (``alone``: on DIN 5008's date line it is strong),
#: alone on the page's first line (``first``) or alone beside an address line (``beside``).
HeaderKind = Literal["label", "column", "place", "alone", "first", "beside"]


class _Dated(NamedTuple):
    """A date the letter gives for itself: ``strong`` when its words name it the letter's own (a "Datum"
    label, a place and date in the header, the reference line), weak otherwise (another "…datum", a date alone,
    a continuation page's); ``kind``: how the header names it (:data:`HeaderKind`); ``own``: a strong date of one
    of the letter's own kinds, which may start the check alone (:func:`_start`) — an own label of its date, the
    reference line's "Datum" column, a place the page names after a postcode, or DIN 5008's date line — not a
    place it names nowhere else ("Abholung am Schalter, …", "Sprechtag, Dienstag, …") nor a date alone on its first
    line."""

    day: date
    strong: bool
    kind: HeaderKind = "label"
    own: bool = False


def _header_dates(page: PageInput, *, first: bool = True) -> list[_Dated]:
    """The dates a page gives for its letter, before its remedy notice: one date that reads one way and ends
    its line, after a date label ("Datum 06.11.2026", "Bescheiddatum:", "Einzugsdatum:" — only a label of the
    letter's own date is strong, never a print or copy date it gets after it, "Druckdatum", nor an English
    "… date:" but "Date:" — and only in the header or on the date line, never an appointment's block "Ihr
    Termin:" / "Datum: …" / "Uhrzeit: …"), after a place ("Musterstadt, (Freitag,) (den) 06.11.2026"; strong
    among the header's lines or on the date line, never under a line ending in ":"), on the reference line
    under a line naming a "Datum" column ("Ihr Zeichen  Unser Zeichen  Datum" over "AB-1  ST-22  06.11.2026":
    its last date, strong, unless a due word stands before it) or — in the page's header, not under a line that
    labels another date ("Antrag vom") — alone (weak; strong on DIN 5008's date line right under the
    recipient's postcode and street). Never a due day, a validity, an appointment or a date after a weekday
    ("Zahlbar bis Freitag, 04.12.2026"); a town on a river ("Frankfurt am Main") is no appointment. A remedy
    word in the letterhead or subject ("Widerspruchsstelle") doesn't end the scan; the notice does. On a page
    after the first (``first`` false) every date is weak."""
    lines = fold_punctuation(join_hyphenated(_visible(page))).splitlines()
    rows = len(header(_unabbreviated(lines)))  # "Dr. Max Probe" ends no header
    greeting = next((at for at, line in enumerate(lines) if _SALUTATION.match(line.strip())), len(lines))
    top = next((at for at, line in enumerate(lines) if line.strip()), -1)  # the page's first line
    towns = _towns("\n".join(lines))
    # the address field's lines: the recipient's postcode line and the (at most three) lines above it, the blank
    # lines a text layer leaves between rows skipped
    posts = [at for at, line in enumerate(lines) if _POSTCODE_START.match(line.strip())]
    address_rows = {
        row
        for post in posts
        for row in [post, *[at for at in range(post - 1, -1, -1) if lines[at].strip()][:3]]
    }
    # the address field and its info block, when columns run into one line cut the header short (no salutation)
    field = _address_field_end(_unabbreviated(lines), rows) if greeting == len(lines) else rows
    found: list[_Dated] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _GERMAN_REMEDY.search(stripped) and (index >= field or _PERIOD_WORDS.search(stripped)):
            break  # the notice: what follows is no date of the letter's (a sign-off, an enclosure's)
        spans = date_spans(stripped)
        label_at = next((at for at in range(index - 1, -1, -1) if lines[at].strip()), -1)
        labels = lines[label_at].strip() if label_at >= 0 else ""
        column = (
            len(spans) == 1
            and bool(_DATUM_COLUMN.search(labels))
            and not _OTHER_DATE.search(labels)
            and not _EVENT.search(f"{labels} {stripped}")  # an appointment's date
            # a payments table ("Datum   Betrag   Kassenzeichen" over "04.12.2026   85,00 EUR …"), no reference line
            and not _MONEY_LABEL.search(labels)
            and not _AMOUNT_CELL.search(stripped)
        )
        if spans and 0 <= label_at <= rows and (_REFERENCE_LABELS.search(labels) or column):
            start, end, mention = spans[-1]
            day = mention.as_date()
            # the words before it on its line (never a reference code: "AB-1", "ST-22"): no due day's
            words = [
                w
                for w in stripped[spans[-2][1] if len(spans) > 1 else 0 : start].split()
                if not re.search(r"\d", w)
            ]
            if (
                day is not None
                and (end == len(stripped) or column)
                and not _OTHER_DATE.search(" ".join(words))
            ):
                found.append(_Dated(day, first, "column", own=first))
            continue
        if len(spans) != 1:
            continue
        start, end, mention = spans[0]
        day = mention.as_date()
        if day is None or end != len(stripped):
            continue
        # "Ort, Datum: Beispielhausen, 06.11.2026": the label of the place and date before them
        before = _PLACE_LABEL.sub("", stripped[:start])
        # right after the recipient's address (DIN 5008's date line): the letter's own date
        filled = [line.strip() for line in reversed(lines[:index]) if line.strip()]
        above = filled[0] if filled else ""
        after_address = (
            bool(_POSTCODE_LINE.match(above))
            and len(filled) > 1
            and bool(_STREET_LINE.search(filled[1]))
            and not _OTHER_DATE.search(_TOWN.sub(" ", _STREET_PREFIX.sub("", filled[1])))
            and index < greeting
        )
        # an address line the text layer ran into the date's line ("Am Lindenhof 2   …") is no label of it
        column_words = _own_column(before)
        kind: HeaderKind = "label"
        own = False
        if _DATE_LABEL.search(before):
            if _AS_OF.search(before) and not (index < field or after_address):
                continue  # an as-of date in the body (an account's statement): no date of the letter's
            other = _OTHER_DATE.search(
                _TOWN.sub(" ", _CREATED_ON.sub(" ", _unaddressed(before)))
            )  # "Fälligkeitsdatum:" is no letter's date
            following = lines[index + 1] if index + 1 < len(lines) else ""
            strong = (
                bool(_OWN_LABEL.search(before))
                and (index < field or after_address)  # not an appointment's "Datum:" in the body
                and not (_BLOCK_ABOVE.search(above) or _BLOCK_BELOW.search(following))  # nor in its block
            )
            own = strong
        elif _PLACE_DATE.match(before) or (column_words is not None and _PLACE_DATE.match(column_words)):
            place = before if _PLACE_DATE.match(before) else column_words or ""
            # "Zahlbar bis Freitag, …"
            other = _OTHER_DATE.search(_TOWN.sub(" ", _unaddressed(place).split(",")[0]))
            strong = (index < field or after_address) and not above.endswith(":")
            kind = "place"
            # a place the page names nowhere else ("Abholung am Schalter"): no start alone
            own = strong and _names_town(
                place, towns, "\n".join(lines[:index]), beside_address=index in address_rows
            )
        elif not before.strip() and (index < rows or after_address):
            # under a line that labels another date ("Antrag vom", "Zahlbar bis Freitag,") — never under a sentence
            # ending there ("Mit diesem Bescheid vom … setzen wir … fest."): a date alone under one stays weak
            sentence = above.endswith(".") and len(above.split()) >= 4
            other = None if sentence else _ANOTHER.search(above) or _OTHER_DATE.search(_TOWN.sub(" ", above))
            below = next((line.strip() for line in lines[index + 1 :] if line.strip()), "")
            # an appointment's time under it ("09:00 Uhr, Raum 2.14") is no date line's — but opening hours are
            # ("Sprechzeiten: Mo–Fr 08:00–12:00 Uhr"), and so is a line naming its own other date ("Meldeaufforderung
            # zum 05.10.2026 um 9:00 Uhr": the time is that date's)
            appointment = bool(
                (_BLOCK_BELOW.search(below) or _TIME_BELOW.search(below))
                and not (_HOURS.search(below) and not _NOT_HOURS.search(below))
                and not any(mention.as_date() not in (None, day) for _lo, _hi, mention in date_spans(below))
            )
            strong = after_address and not appointment
            kind = "alone"
            own = strong
            if own and first:
                # a date the page names as its own at its foot ("Beispielhausen, den 06.11.2026" over the signature)
                # lowers the date line's: that one may be a received stamp in its place ("20.11.2026" under the address)
                found += [_Dated(closing, False, "alone") for closing in sorted(_named_own(lines) - {day})]
            if index == top and first and not strong and not appointment:
                # the page's first line (a transcript that writes the date first): the letter's own when its header
                # gives no other date (one there may be its own, unread: then this one only lowers the start)
                strong, kind = True, "first"
                own = not any(
                    date_spans(other) for at, other in enumerate(lines[: max(rows, field)]) if at != index
                )
                # a date the page names as its own elsewhere — a closing "Beispielhausen, den 06.11.2026" under the
                # notice — lowers it: this one may be a stamp or the day the letter arrived, written at its top by
                # hand ("20.11.2026" over "EINGANG"); more than LETTER_DATE_SPAN days earlier, no start at all
                if own:
                    found += [
                        _Dated(closing, False, "alone") for closing in sorted(_named_own(lines) - {day})
                    ]
        elif before.endswith(_COLUMN) and _beside_address(before) and (index < field or after_address):
            # alone in its column beside an address line the text layer ran into it ("Probeweg 2   06.11.2026"):
            # weak — it only ever lowers the start (or voids it), never sets one
            label = above.rsplit(_COLUMN, 1)[-1] if _COLUMN in above else above
            if _COLUMN in above and not _OWN_LABEL.search(label):
                continue  # the value under another field's label in its column ("Ihre Nachricht", "Ihr Schreiben")
            other = _ANOTHER.search(label) or _OTHER_DATE.search(_TOWN.sub(" ", label))
            strong = False
            kind = "beside"
        else:
            continue
        if other is None:
            found.append(_Dated(day, strong and first, kind, own=own and strong and first))
    return found


def _named_own(lines: Sequence[str]) -> set[date]:
    """The dates a page names as its own on any of its lines — a place and date not under a label ("Beispielhausen, den
    06.11.2026" above the signature, never "Ortstermin:" over one) or an own date's label ("Datum: …") — wherever they
    stand, under the notice too."""
    days: set[date] = set()
    for index, line in enumerate(lines):
        stripped = line.strip()
        spans = date_spans(stripped)
        if len(spans) != 1 or spans[0][1] != len(stripped) or (day := spans[0][2].as_date()) is None:
            continue
        before = _PLACE_LABEL.sub("", stripped[: spans[0][0]])
        above = next((lines[at].strip() for at in range(index - 1, -1, -1) if lines[at].strip()), "")
        place = bool(_PLACE_DATE.match(before)) and not above.endswith(":")
        other = _OTHER_DATE.search(_TOWN.sub(" ", before.split(",")[0]))
        if (place and not other) or _OWN_LABEL.search(before):
            days.add(day)
    return days


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

    * **strong** dates set it: the reading's and those of the letter's own kinds (:func:`_dates`: the first page's
      "Datum:" and "mit diesem Bescheid vom …", :func:`~ordnung.ingest.conflicts.letter_statements`, its header
      dates of an own kind, :attr:`_Dated.own`, and the decision its notice names, "Bescheid vom …"). None when
      there is none, or when they are more than :data:`LETTER_DATE_SPAN` days apart (one of them is another's:
      planted, a due day, an old decision's);
    * **weak** dates only lower it, within that span of the strong ones — one earlier still leaves no start, as two
      strong ones would; one later than every strong date is another's and is ignored. Weak are another "…datum",
      a date alone, a continuation page's, "Schreiben vom …" — and a date named like the letter's own but of no own
      kind: a place the page names nowhere else ("Abholung am Schalter, …", "Sprechtag, Dienstag, …"), a date alone
      on the date line with an appointment's time under it, one alone on the first line beside another date of the
      header. So while the letter's own date is unread, such a line — planted later, or an appointment's — starts
      nothing without the reading's date beside it. A date the page names as its own at its foot ("Beispielhausen,
      den 06.11.2026" over the signature) is a weak date of a letter whose first line or date line holds a date
      alone: that one may be a received stamp (:func:`_named_own`);
    * a start that rests on one date alone, more than :data:`STALE_DAYS` before ``today`` (the day the letter
      arrived, or was read), is no start: never an overdue to-do from a stray date; nor is one after ``today``
      (a misprint, a post-dated letter);
    * on a decision on a remedy (a Widerspruchsbescheid) dated only by the decision its notice names, a date of
      the letter's far later means that one is the decision it reshapes: no start."""
    notices = remedy_notices(pages) if notices is None else notices
    dated = _dates(extraction, pages, notices)
    # a notice restating another decision's, whose date the letter never gives, on a letter that sends or reminds of
    # that decision and never names itself one (a cover letter, a reminder): its period runs from that decision
    visible = "\n".join(_visible(page) for page in pages)
    if (
        any(notice.restates for notice in notices)
        and (
            _SENDS_DECISION.search(visible) or (_REMINDS.search(visible) and not _DECIDES_NOW.search(visible))
        )
        and not _NAMES_ITSELF.search(visible)
    ):
        return _Start(None, True)
    own = [
        *dated.own,
        *([dated.read] if dated.read is not None else []),
    ]  # not the decisions its notice names
    strong = [*own, *dated.issued]
    weak = [*dated.weak, *dated.other]
    on_remedy = any(_ON_REMEDY.search(notice.text) for notice in notices)
    found = bool(strong or weak)
    if not strong:
        return _Start(None, found)
    first, last = min(strong), max(strong)
    if (last - first).days > LETTER_DATE_SPAN:
        return _Start(None, found)
    earlier = [day for day in weak if day < first]
    if any((last - day).days > LETTER_DATE_SPAN for day in earlier):
        return _Start(None, found)
    # a decision on a remedy (a Widerspruchsbescheid) dated only by the decision its notice names, and a date of
    # the letter's far later: that decision is the one it reshapes (an old one), never this letter's start
    if on_remedy and not own and any((day - last).days > LETTER_DATE_SPAN for day in weak):
        return _Start(None, found)
    first = min([first, *earlier])
    # no other date of the letter's near it (a later one far off is another's, but no support either)
    alone = not any(day != first and abs((day - first).days) <= LETTER_DATE_SPAN for day in (*strong, *weak))
    if today is not None and first > today:
        return _Start(None, found)  # dated after it arrived: a misprint, never a start
    if alone and today is not None and (today - first).days > STALE_DAYS:
        return _Start(None, found)
    return _Start(first, found)


class _Dates(NamedTuple):
    """The dates a letter gives for itself (:func:`_start`): ``own`` — of one of its own kinds, which set the
    start; ``issued`` — the decisions its notice names ("Bescheid vom …"), which set it too; ``other`` — named like
    its own but of no own kind, which only lower it (a place the page names nowhere else); ``weak``; ``read`` —
    the reading's."""

    own: list[date]
    issued: list[date]
    other: list[date]
    weak: list[date]
    read: date | None


def _dates(
    extraction: DocumentExtraction, pages: Sequence[PageInput], notices: Sequence[RemedyNotice] | None
) -> _Dates:
    """The letter's dates for itself by how they are named (:class:`_Dates`)."""
    own = [statement.letter_date for statement in letter_statements(pages) if statement.letter_date]
    issued: list[date] = []
    other: list[date] = []
    weak: list[date] = []
    stamp: date | None = None
    for index, page in enumerate(pages):
        for dated in _header_dates(page, first=index == 0):
            (own if dated.own else other if dated.strong else weak).append(dated.day)
            if index == 0 and dated.own and dated.kind == "first":
                stamp = dated.day
    if stamp is not None:
        # a date alone on the first line may be a received stamp: a date a later page names as the letter's own (the
        # closing "Beispielhausen, den 06.11.2026" on its last page) lowers it, as one on the first page does
        for page in pages[1:]:
            weak += sorted(
                _named_own(fold_punctuation(join_hyphenated(_visible(page))).splitlines()) - {stamp}
            )
    for notice in notices if notices is not None else remedy_notices(pages):
        issued += notice.issued
        weak += notice.mentioned
    return _Dates(own, issued, other, weak, _iso(extraction.document_date))


def _letter_dates(
    extraction: DocumentExtraction, pages: Sequence[PageInput], notices: Sequence[RemedyNotice] | None
) -> tuple[list[date], list[date]]:
    """The letter's strongly named and weak dates for itself, the reading's among the strong (:func:`_dates`)."""
    dated = _dates(extraction, pages, notices)
    strong = [*dated.own, *dated.other, *dated.issued]
    return ([*strong, dated.read] if dated.read is not None else strong), dated.weak


def _own_start(pages: Sequence[PageInput]) -> date | None:
    """The date the letter's first page names as its own (a "Datum" label, a place and date in its header, the
    reference line, the date line, "mit diesem Bescheid vom …", a date alone on its first line when the header gives
    no other), never the reading's, a bare or a continuation page's date: the earliest when they are within
    :data:`LETTER_DATE_SPAN` days, else the latest. Only ever a rival that lowers a reading's date
    (:func:`notice_rival`), so a place named nowhere else counts here too: a later start only weakens it."""
    days = [statement.letter_date for statement in letter_statements(pages[:1]) if statement.letter_date]
    days += [
        dated.day
        for dated in (_header_dates(pages[0]) if pages else [])
        if dated.strong and (dated.own or dated.kind != "first")
    ]
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

    # after a Widerspruchsbescheid or an Einspruchsentscheidung only a court action is left: it names a tie
    after_remedy = (
        bool(_DECIDED_REMEDY.search(text))
        and any(n.remedy == "klage" for n in notices)
        and (
            bool(_SELF_DECIDED.search(text))  # it names itself the decision on the remedy
            or not any(
                n.remedy != "klage" and n.live and _THIS_FIRST_DECISION.search(n.text) for n in notices
            )
        )
    )

    def order(start_day: date | None, pick: tuple[RemedyNotice, tuple[int, Unit]]) -> tuple[object, ...]:
        notice, period = pick
        length = _end(start_day, period) if start_day else period[0] * _DAYS[period[1]]
        return (
            length,
            period[0] * _DAYS[period[1]],
            (notice.remedy == "klage") != after_remedy,
            notice.notified,
        )

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
    Without one — or for an almost blank reading when no notice is live and every one can be dated (a remedy
    the letter rules out) — a ``task``: read the letter."""
    notices = remedy_notices(pages)
    gap = reading_gap(extraction, pages, notices)
    if gap is None:
        return None
    if not notices or (gap == "empty" and not any(notice.live or not notice.datable for notice in notices)):
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
    no rival. A notice from notification is ranked from its latest deemed delivery (up to four days on), so a
    month from service beats a month from notification; on a tie the one from notification. ``Rival.served``
    when its own words count from service or arrival ("nach Zustellung"), so it starts on an arrival the person
    confirmed; a notice from notification on a letter served formally keeps the letter's date (the envelope's
    date may be earlier than a late arrival, a pickup at the post office or a date saved weeks later)."""
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
    formal = bool(_FORMAL_SERVICE.search(text))
    shift = {True: timedelta(days=4), False: timedelta(0)}
    notice, period = min(
        picks,
        key=lambda pick: (
            _end(start + shift[pick[0].notified and not formal], pick[1]),
            not pick[0].notified,
        ),
    )
    delivery: Literal["de_admin_post", "de_admin_portal", "none"] = "none"
    if notice.notified and not formal:
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
    served = bool(_ARRIVAL.search(notice.text))  # formal service alone never moves it to an arrival
    return Rival(spec, notice.quote, notice.grounding, notice=True, served=served)


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
    deadlines = [item for item in items if is_check_slot(item.slot_key) and item.slot_key != CHECK_SLOT]
    kept: list[str] = []
    for warning in warnings:
        if warning.strip().startswith(DEADLINE_WARNING_PREFIX):
            if any(
                needs_check(item) for item in deadlines
            ):  # gone once each date the reading left out was dealt with
                kept.append(warning)
        elif not GAP_WARNING.match(warning.strip()):
            kept.append(warning)
        elif pending:
            dated = any(item.due_date for item in pending)
            kept.append(warning.replace(_SUFFIX["undated"], _SUFFIX["dated"]) if dated else warning)
    return kept


def check_reasons(reasons: Sequence[str], slot: str = CHECK_SLOT) -> tuple[str, ...]:
    """The reasons a code-made to-do is graded by: always :data:`READING_INCOMPLETE`, or for a date the reading
    left out (``slot``: :data:`DEADLINE_SLOT`) :data:`~ordnung.ingest.verify.DEADLINE_LEFT_OUT`; never that its
    quote doesn't state the start date or the period (Ordnung took them from the letter, not from that sentence)."""
    own = READING_INCOMPLETE if slot == CHECK_SLOT else DEADLINE_LEFT_OUT
    kept = tuple(reason for reason in reasons if reason not in (DATE_NOT_IN_QUOTE, PERIOD_NOT_IN_QUOTE))
    return kept if own in kept else (*kept, own)


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
    envelope = envelope_start(spec, ctx)
    if envelope is not None:
        # served with a Postzustellungsurkunde: the envelope's date the person entered is the start, that alone
        return [(spec.model_copy(update={"anchor_date": envelope.isoformat()}), plain)]
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


# --------------------------------------------------------------------------------------------------
# An explicit date the letter sets that the reading left out (check:deadline)
# --------------------------------------------------------------------------------------------------

#: Slot of a to-do code files for a fixed date the letter's own words set for the person (pay by, send by) that the
#: reading left out: ``check:deadline#<date>-<nature>``, one per date and kind (:func:`deadline_slots`).
DEADLINE_SLOT = "check:deadline"
#: How many days a dated to-do of the reading may stand from such a date and still be its own (a weekend moved, a
#: send-by day taken for the due day).
DEADLINE_REACH = 3
_WEEKDAY_WORD = (
    r"(?:(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag|monday|tuesday|wednesday"
    r"|thursday|friday|saturday|sunday),?\s*)?"
)
#: "bis (zum | spätestens (zum | am)) (Freitag,) (den)" right before the date.
_BY = rf"\bbis\s+(?:(?:zum|einschließlich|spätestens(?:\s+(?:zum|am))?)\s+)?{_WEEKDAY_WORD}(?:den\s+)?$"
#: A payment's label right before the date ("Zahlbar bis", "Fällig am:", "Fälligkeit:", "Zahlungsziel:", "Due date:").
_PAY_LABEL = re.compile(
    r"(?:^|[\s(·|])(?:zahlbar|fällig|fälligkeit|fälligkeitsdatum|zahlungsziel|zahlungstermin|due\s+date|payable)"
    rf"(?:\s+(?:bis|am|zum|by|on))?(?:\s+(?:zum|spätestens|am))?\s*:?\s*{_WEEKDAY_WORD}(?:den\s+)?$",
    re.IGNORECASE,
)
#: The person asked to pay by the date: "Bitte überweisen Sie den Betrag … bis zum", "please pay … by".
_PAY_YOU = re.compile(
    rf"\b(?:überweisen|zahlen|begleichen|entrichten)\s+sie\b(?:[^.;:!?]|\.(?=\d)){{0,120}}?{_BY}"
    r"|\bplease\s+(?:pay|transfer)\b(?:[^.;:!?]|\.(?=\d)){0,120}?\b(?:by|before|no\s+later\s+than)\s+(?:the\s+)?$"
    r"|\b(?:payment|amount|balance|total)\s+(?:is\s+)?due\s+(?:by|on)\s+(?:the\s+)?$",
    re.IGNORECASE,
)
#: … "bis zum <date> zu zahlen": the date's own clause goes on with the payment.
_PAY_AFTER = re.compile(
    r"^\s*(?:[^\s.;:!?,]+\s+){0,3}?(?:zu\s+(?:zahlen|überweisen|begleichen|entrichten)|zur\s+zahlung\s+fällig|fällig)\b",
    re.IGNORECASE,
)
#: … "ist am <date> fällig", "wird zum <date> fällig".
_DUE_BEFORE = re.compile(r"\b(?:bis\s+(?:zum\s+)?|am\s+|zum\s+)$", re.IGNORECASE)
_DUE_AFTER = re.compile(r"^\s*(?:zur\s+zahlung\s+)?fällig\b", re.IGNORECASE)
#: The person asked to send or hand in something by the date: "Bitte reichen Sie … bis zum … ein", "senden Sie …
#: zurück", "teilen Sie uns … mit", "please submit / return / send … by".
_SEND_YOU = re.compile(
    rf"\b(?:reichen|senden|schicken|legen|geben|teilen|übersenden|übermitteln)\s+sie\b(?:[^.;:!?]|\.(?=\d)){{0,120}}?{_BY}"
    r"|\bplease\s+(?:submit|return|send)\b(?:[^.;:!?]|\.(?=\d)){0,120}?\b(?:by|before|no\s+later\s+than)\s+(?:the\s+)?$",
    re.IGNORECASE,
)
#: … the separable verb's prefix after the date ("… bis zum 15.10.2026 ein"), unless the verb has none.
_SEND_PREFIX = re.compile(r"^[^.;:!?]{0,60}?\b(?:ein|zurück|vor|ab|mit|nach|zu)\b", re.IGNORECASE)
_SEND_WHOLE = re.compile(
    r"\b(?:übersenden|übermitteln)\s+sie\b|\bplease\s+(?:submit|return|send)\b", re.IGNORECASE
)
#: … "bis spätestens <date> vorzulegen", "bis zum <date> einzureichen".
_SEND_AFTER = re.compile(
    r"^\s*(?:[^\s.;:!?,]+\s+){0,3}?(?:einzureichen|vorzulegen|zurückzusenden|zurückzugeben|abzugeben|nachzureichen"
    r"|mitzuteilen|zu\s+übersenden|zu\s+übermitteln)\b",
    re.IGNORECASE,
)
#: A reading's warning that calls the letter a scam (as the benchmark and the scam Idea read one).
_SCAM = re.compile(
    r"scam|phish|fraud|betrug|betrüg|fake|gefälscht|suspicious|verdächtig|imperson|not legitimate|illegitimate|"
    r"unseriös|abzocke|counterfeit|bogus",
    re.IGNORECASE,
)
#: A reading's warning that doubts the payment itself — its account or payee, or whether it is owed ("The payee account
#: is a Lithuanian IBAN …", "Check whether you really owe this money before paying"): a payment it left out may be left
#: out on purpose, and is never brought back.
_PAY_DOUBT = re.compile(
    r"\biban\b|\bpayee\b|empfänger|\baccount\b|\bkonto\b|creditor|gläubiger|\bowed?\b|mismatch"
    r"|\bdo\s+not\s+pay|\bdon'?t\s+pay|before\s+(?:you\s+)?pay|nicht\s+(?:be)?zahlen|nicht\s+überweisen",
    re.IGNORECASE,
)
#: A sentence whose date is no deadline of the person's: a condition, something past or already done, the sender's
#: own act or a direct debit (money it collects or pays out), an appointment, a discount, a preference, a validity —
#: or an option the person may take ("Bei Interesse senden Sie …", "Um am Bonusprogramm teilzunehmen, …", "Zur
#: Auftragserteilung …", "Sie können Ihre Einwilligung jederzeit widerrufen; senden Sie …", "… und sichern Sie sich
#: 5 % Treuebonus"), never a request with a reason ("Um über Ihren Antrag entscheiden zu können, reichen Sie …").
_NOT_OWED = re.compile(
    r"\b(?:falls|wenn|sofern|sollten|soweit|if|unless|should\s+you)\b"
    r"|\b(?:war|waren|wurde|wurden|hatte|hatten|was|were|had|bereits|schon|already)\b"
    r"|\b(?:wir|we)\s+(?:\w+\s+){0,2}?(?:überweisen|zahlen|buchen|ziehen|erstatten|senden|schicken|werden|will|shall)\b"
    r"|abbuch|abgebucht|lastschrift|\beinzug|eingezogen|\bsepa\b|gutschrift|erstatt|auszahl|direct\s+debit|refund"
    r"|\btermin\w*|\buhr\b|\berscheinen\b|\bvorsprache\b|\bappointment\b|\b\d{1,2}:\d{2}\b"
    r"|skonto|discount|rabatt|nachlass|abzüglich|möglichst|wenn\s+möglich|vorzugsweise|if\s+possible|preferably"
    r"|\bgilt\b|gültig|\bläuft\b|\bvalid\b"
    r"|\bbei\s+interesse\b|\bauftragserteilung\b|bonus"
    r"|\bum\s+(?:\w+\s+){0,6}?(?:teilzunehmen|anzunehmen|wahrzunehmen|zu\s+nutzen)\b"
    r"|(?<!\bwir\s)\bmöchten\s+sie\b|\bsie\s+(?:möchten|wünschen)\b|\bwünschen\s+sie\b"
    r"|^\s*(?:andernfalls|ansonsten)\b|\bjederzeit\s+(?:\w+\s+){0,2}?(?:widerrufen|kündigen|ändern)\b",
    re.IGNORECASE,
)
#: A question that offers the person an option ("Sie möchten Ihren Vertrag nicht verlängern?", "Möchten Sie Ihren
#: Tarif wechseln?"): the request after it ("Dann senden Sie uns … bis zum … zu.") is that option's, no deadline —
#: never a W-question heading ("Was müssen Sie tun?") nor "Haben Sie Fragen?".
_OPTION_ASKED = re.compile(
    r"\b(?:möchten|wollen|wünschen|interessier\w*|planen|benötigen|brauchen|would\s+you\s+like|do\s+you\s+want"
    r"|interested)\b[^?]*\?\s*$",
    re.IGNORECASE,
)
_W_QUESTION = re.compile(
    r"^\s*(?:was|wie|wann|wo\w*|warum|weshalb|wieso|welche\w*|wer|wen|wem|what|how|when|where|why|which|who)\b",
    re.IGNORECASE,
)
#: A period's end right before the date ("für den Zeitraum (vom …) bis zum", "für die Zeit bis zum", "für das
#: Kita-Jahr bis zum"): the end of what the payment is for, never the day it is due — the period's noun a whole word
#: ("Jahresbeitrag bis zum", "Monatsbeitrag bis zum" are payments).
_PERIOD_END = re.compile(
    r"(?<![\w-])(?:[a-zäöüß]+-)?(?:\w*zeitraum|zeit|monat|quartal|halbjahr|jahr|kalenderjahr|schuljahr|beitragsjahr)"
    r"\s+(?:vom\s+\S+\s+)?bis\s+(?:(?:zum|einschließlich)\s+)?(?:den\s+)?$",
    re.IGNORECASE,
)
#: The full price after a discount's date ("Zahlbar bis 31.10.2026 ohne Abzug", "… netto", "… ohne Skonto"): beside
#: a payment of the reading (dated by the discount's day) the same obligation, never another.
_FULL_PRICE = re.compile(r"\bohne\s+(?:abzug|skonto)\b|\bnetto\b|\bwithout\s+discount\b", re.IGNORECASE)
#: The letter says its whole amount is paid already ("Der Rechnungsbetrag wurde bereits per PayPal beglichen", "Betrag
#: dankend erhalten", "Status: bezahlt") or is a credit note (a heading "Gutschrift"): a "Fälligkeitsdatum:" or
#: "Zahlungsziel:" box on it sets no payment of the person's — never a condition ("Sollten Sie den Betrag bereits
#: bezahlt haben, …") nor a part ("Ein Teilbetrag wurde bereits bezahlt").
_SETTLED = re.compile(
    r"\b(?:rechnungsbetrag|gesamtbetrag|betrag|rechnung|rechnungssumme|summe)\s+(?:\w+\s+){0,4}?"
    r"(?:beglichen|bezahlt|gezahlt|erhalten|ausgeglichen|eingegangen)\b"
    r"|status\s*:?\s*(?:bezahlt|beglichen|paid)\b|\b(?:paid\s+in\s+full|already\s+(?:been\s+)?paid)\b"
    # "Bezahlt am 01.10.2026 per PayPal", "Bezahlt mit PayPal", "Zahlungsart: PayPal (bezahlt)"
    r"|^\s*bezahlt\s+(?:am|mit|per|via|über)\b|\(\s*bezahlt\s*\)"
    # "Zahlung erhalten am …", "Wir haben Ihre Zahlung erhalten", "Zahlung dankend erhalten"
    r"|\bzahlung\s+(?:\w+\s+){0,2}?(?:erhalten|eingegangen)\b|\bihre\s+zahlung\s+(?:\w+\s+){0,2}?erhalten\b"
    r"|^\s*(?:rechnungskorrektur\s*/\s*)?gutschrift\b[^\n.]{0,40}$",
    re.IGNORECASE | re.MULTILINE,
)
#: The letter pays money out to the person ("Erstattung", "Auszahlung", "Der Betrag wird auf Ihr Konto überwiesen",
#: "überweisen wir Ihnen"): a "Fällig am:" or "Zahlungstermin:" box on it is the day it pays, never the person's.
_PAID_OUT = re.compile(
    r"erstattung|auszahlung"
    # "Das Wohngeld wird monatlich im Voraus auf Ihr Konto überwiesen", "… wird Ihrem Konto gutgeschrieben"
    r"|\bwird\s+(?:ihnen\s+)?(?:[\w-]+\s+){0,5}?(?:auf\s+ihr(?:em)?\s+konto\s+|ihrem\s+konto\s+)?"
    r"(?:überwiesen|ausgezahlt|erstattet|gutgeschrieben)\b"
    # "Wir überweisen den Betrag auf Ihr Konto", "Wir zahlen den Betrag auf Ihr Konto", "Die Zahlung erfolgt auf Ihr Konto"
    r"|\b(?:überweisen|erstatten|zahlen)\s+wir\b|\bwir\s+(?:überweisen|erstatten|zahlen)\b|\bzahlung\s+erfolgt\s+(?:\w+\s+){0,3}?auf\s+ihr\b|\bguthaben\b",
    re.IGNORECASE,
)
#: A part still owed or asked for beside it ("Restbetrag", "Nachzahlung", "noch offen", "Bitte überweisen Sie …"):
#: then the box may be that part's.
_STILL_OWED = re.compile(
    r"rest(?:betrag|zahlung|forderung)|verbleibend|nachzahlung|\bnoch\s+offen|offene[nrs]?\s+(?:betrag|forderung|posten)"
    r"|ausstehend|\bzu\s+(?:zahlen|überweisen|entrichten)\b|\b(?:zahlen|überweisen|begleichen)\s+sie\b",
    re.IGNORECASE,
)
_CONDITION_WORDS = re.compile(r"\b(?:falls|wenn|sofern|sollten?|soweit|if|should)\b", re.IGNORECASE)
#: A debit offered or wished for rather than done ("Tipp: Zahlen Sie künftig bequem per SEPA-Lastschrift", "Gerne
#: können Sie uns ein Lastschriftmandat erteilen"): no debit of this letter's.
_DEBIT_OFFERED = re.compile(
    r"\b(?:künftig|zukünftig|gerne?|tipp|bequem|können\s+sie|möchten\s+sie|wenn|falls|sofern|sollten)\b",
    re.IGNORECASE,
)


def _collected_by_debit(pages: Sequence[PageInput]) -> bool:
    """The letter collects its money by direct debit (``ordnung.payments``' policy): a sentence of it names a debit
    (:func:`~ordnung.payments.debit_in_sentence`) as done, not offered (:data:`_DEBIT_OFFERED`), none says a debit
    failed, and none asks for a transfer — so a "Fällig am:" box beside "Den Betrag buchen wir per SEPA-Lastschrift
    ab." is no payment of the person's."""
    from ordnung.payments import _NO_TRANSFER, _TRANSFER_WORDS, debit_failed, debit_in_sentence
    from ordnung.payments import _clauses as payment_clauses

    text = "\n".join(_visible(page) for page in pages)
    return (
        any(
            debit_in_sentence(sentence) and not _DEBIT_OFFERED.search(sentence)
            for sentence in sentences(text)
        )
        and not debit_failed(text)
        # a transfer it asks for anywhere ("Bitte überweisen Sie die Nachzahlung …"), not one it waves off
        and not any(
            _TRANSFER_WORDS.search(clause) and not _NO_TRANSFER.search(clause)
            for clause in payment_clauses(text)
        )
    )


def _not_owed_by_label(pages: Sequence[PageInput]) -> bool:
    """A payment's label ("Fällig am:", "Zahlungsziel:") or "fällig" on the letter sets no payment of the person's:
    it collects by direct debit (:func:`_collected_by_debit`), says its whole amount is paid or is a credit note
    (:data:`_SETTLED`), or pays money out (:data:`_PAID_OUT`) — the last two only when nothing on it is still owed or
    asked for (:data:`_STILL_OWED`). A "Bitte überweisen Sie … bis" is never waved off so."""
    if _collected_by_debit(pages):
        return True
    said = [sentence for page in pages for sentence in sentences(_visible(page))]
    if any(_STILL_OWED.search(sentence) for sentence in said):
        return False
    return any(
        (_affirmed(_SETTLED, sentence) or _affirmed(_PAID_OUT, sentence))
        and not _CONDITION_WORDS.search(sentence)
        for sentence in said
    )


#: A negation in or right before such a statement ("bisher nicht erhalten", "keine Zahlung eingegangen", "noch nicht
#: beglichen", "Eine Erstattung ist nicht möglich"): the amount is not paid, nor paid out.
_NOT_SO = re.compile(r"\b(?:nicht|kein\w*|niemals|ausstehend\w*)\b", re.IGNORECASE)


def _affirmed(pattern: re.Pattern[str], sentence: str) -> bool:
    """Whether ``pattern`` matches ``sentence`` without a negation in the match, in the 15 characters before it or in
    the rest of its clause (:data:`_NOT_SO`)."""
    for found in pattern.finditer(sentence):
        after = re.split(r"[;,]", sentence[found.end() :], maxsplit=1)[0]
        if not _NOT_SO.search(sentence[max(0, found.start() - 15) : found.end()]) and not _NOT_SO.search(
            after
        ):
            return True
    return False


#: A deadline's own label word ("Zahlungsfrist", "Abgabefrist", "Rücksendefrist").
_DUE_FRIST = r"(?:zahlungs|überweisungs|abgabe|rücksende|rücksendungs|rückgabe|vorlage|einreichungs|einsende|nachreichungs)frist"


_Kind = Literal["payment", "declaration"]

# -- what keeps a looser wording's date from being the person's (each read in the date's own sentence) -------------

#: Words in a sentence that keep a looser wording's date from being the person's deadline, beside
#: :data:`_NOT_OWED`: a negation ("Geht Ihre Zahlung nicht bis … ein", "Erhalten wir bis … keine Antwort" — never
#: "no later than"), a condition's start ("Sollte der Betrag …", "Ohne Ihre Rückmeldung bis …", "Bei Zahlung bis …
#: reduziert sich …", "Wer bis … zahlt"), an option ("… können … gestellt werden", "ist … möglich", "freiwillig",
#: "Gelegenheit", "may", "can"), a cancellation or renewal ("Die Kündigung muss uns bis … vorliegen, damit …", "If you do
#: not want the policy to renew …"), a period run out ("verstrichen", "abgelaufen"), a statement's cut-off
#: ("Zahlungseingänge bis … wurden berücksichtigt"), a discount's saving and a debit's earliest day.
_LOOSE_NOT_OWED = re.compile(
    r"\b(?:nicht|nie|niemals|not|never)\b(?!\s+(?:später|later)\b)|\bkein\w*|\bno\b(?![.:]|\s+later\b|\s*\d)"
    r"|(?:^|[,;:(–—-])\s*(?:sollte|should|ohne|without)\b|(?-i:\n\s*(?:Sollte|Ohne)\b)"
    r"|\bbei\s+(?:[\w-]+\s+){0,2}?\w{0,20}(?:zahlung|überweisung|eingang|anmeldung|abgabe|buchung|bestellung)\w{0,10}"
    r"\s+(?:bis|vor)\b"
    r"|\bwer\b|\bwhoever\b"
    r"|\b(?:sie|you)\s+(?:\w+\s+)?(?:kann|können|könnten|darf|dürfen|may|can|could)\b"
    r"|\b(?:kann|können|könnten|darf|dürfen|may|can|could)\s+(?:sie|you)\b"
    r"|\b(?:kann|können|könnten|darf|dürfen)\b(?:[^.;:!?]|\.(?=\d)){0,80}?\bwerden\b|\b(?:may|can|could)\s+be\b"
    r"|\b(?:möglich\w*|möglichkeit\w*|freiwillig\w*|gerne?|optional|gelegenheit|interested)\b"
    r"|\b(?:if\s+)?you\s+wish\b|\bwish\s+to\b|\bwould\s+like\b|(?<!\bwir\s)\b(?:möchte\w*|wünsch\w*)\b(?!\s+wir\b)"
    r"|\bkündig\w*|\bgekündigt\b|\bcancel\w*|\brenew\w*|\bwiderruf\w*|\bstorn\w*|\bopt\s*-?\s*out\b"
    r"|\banmeld\w*|\bbewerb\w*|\bgewinnspiel\w*|\bverlosung\w*|\bregist\w*|\benrol\w*|\bsign\s+up\b"
    r"|verstrichen|abgelaufen|versäumt|überschritten|\bpassed\b|\bexpired\b|\blapsed\b"
    r"|berücksichtigt|\benthalten\b|\bincluded?\b|\bshown\b|\bapplied\b"
    r"|reduziert|ermäßig\w*|\b(?:sparen|ersparnis|ersparen)\b|\bsaves?\b|vergünstig\w*|frühbucher\w*"
    r"|frühestens|\bearliest\b",
    re.IGNORECASE,
)
#: Someone other than the person and the sender, anywhere in the sentence: their act, their money or their deadline
#: is none of the person's ("Der Bericht des Gutachters muss …", "Wir erwarten die Antwort der Versicherung …", "Die
#: Zahlung der Miete durch das Jobcenter …", "… beim Finanzamt eingehen", "die Bescheinigung Ihres Vermieters", "Wir
#: haben der Gegenseite eine Frist … gesetzt", "The form must be submitted by your employer …"). A word of the
#: sender's own name is no other party (a Sparkasse's letter names the Sparkasse).
_THIRD_PARTY = re.compile(
    r"\b(?:\w{0,20}arbeitgeber\w{0,3}|\w{0,20}vermieter(?:in|innen|s|n)?|hausverwaltung\w{0,3}|\w{0,20}verwalter(?:in|s)?"
    r"|(?:unter|haupt)?mieter(?:in|innen|s|n)?|gegenseite|gegner(?:in|s)?|gegnerische\w{0,3}|beklagte[nr]?"
    r"|kläger(?:in|s)?|gläubiger(?:in|s)?|gutachter(?:in|s)?|gutachten|sachverständige[nr]?|\w{0,20}gericht(?:s|es)?"
    r"|behörde\w{0,2}|(?:finanz|landrats|ordnungs|sozial|jugend|bürger|standes|einwohnermelde|hauptzoll|zoll"
    r"|gesundheits|arbeits|versorgungs|wohnungs|bau|steuer|kreis|bezirks|grundbuch|nachlass)amt(?:s|es)?"
    r"|jobcenter\w{0,2}|arbeitsagentur|\w{0,20}kasse|versicherer\w{0,2}|lieferant(?:en|in)?|handwerker\w{0,2}"
    r"|banken|bank|steuerberater\w{0,4}|notar\w{0,4}|employers?|landlords?|letting\s+agents?|tenants?|insurers?"
    r"|court|tribunal|other\s+party|council)\b"
    r"|\bder\s+versicherung\b|\b(?:die|ihre)\s+versicherung\s+(?:hat|muss|wird|zahlt|überweist|erstattet|leistet)\b",
    re.IGNORECASE,
)
#: The sender's own act or decision, or its estimate ("Wir erwarten die Entscheidung über Ihren Antrag bis …", "Die
#: Frist für die Prüfung Ihres Antrags endet am …", "… und melden uns bis …", "Unsere Stellungnahme an das Gericht muss
#: bis … erfolgen", "Die Unterlagen müssen von uns … eingereicht werden", "voraussichtlich", "We expect to make a
#: decision …", "Your application is expected to be processed by …", "We are required to send you …") — read with a
#: purpose of the sender's struck out (:data:`_PURPOSE`: "Damit wir Ihren Antrag bearbeiten können, benötigen wir …").
_SENDER_ACTS = re.compile(
    r"\b(?:entscheidung\w{0,3}|entscheiden|entschieden|bearbeitung\w{0,3}|bearbeiten|bearbeitet|prüfung\w{0,3}"
    r"|abschluss|abschließen|abgeschlossen|bewilligung\w{0,3}|genehmigung\w{0,3}|voraussichtlich\w{0,3}"
    r"|unser(?:e|en|em|er|es)?\s+(?:[\w-]+\s+)?(?:stellungnahme|bericht|antwort|schreiben|bescheid|entscheidung"
    r"|zahlung|überweisung|schriftsatz|antrag|rückmeldung|nachricht|abrechnung)"
    r"|von\s+uns|durch\s+uns|melden\s+uns|wir\s+melden|wir\s+(?:\w+\s+){0,3}?(?:prüfen|entscheiden|bearbeiten"
    r"|informieren|benachrichtigen|kümmern|erledigen|veranlassen|einreichen|vorlegen|übermitteln|beantragen"
    r"|erstellen|zusenden|zuschicken|mitteilen|halten)|(?:erledigen|kümmern|veranlassen)\s+wir"
    r"|decision\w{0,2}|decide[ds]?|(?:issued|processed|reviewed|assessed|approved)|processing|by\s+us"
    r"|we\s+are\s+(?:required|obliged)|we\s+(?:will|shall|aim\s+to|plan\s+to|intend\s+to|hope\s+to)\s+"
    r"(?!(?:need|require|expect|receive|hear|have)\b)\w+|expect\s+to\s+(?!(?:receive|hear|have)\b)\w+"
    r"|(?:etwa|ca|rund|circa|ungefähr|about|around|up\s+to)\s+\w+\s+(?:tage|tagen|wochen|monate|days|weeks|months))\b"
    # "Die Rückmeldung zu Ihrem Antrag erwarten wir …": the sender's answer on the person's matter, never hers
    r"|(?<!\bihre\s)(?<!\bihren\s)(?<!\bihrer\s)(?<!\bihrem\s)(?<!\byour\s)\b(?:rückmeldung|antwort|nachricht"
    r"|mitteilung|stellungnahme|response|reply|answer)\s+(?:zu|auf|über|zum|zur|to|on|about)\s+"
    r"(?:ihre[mnrs]?|dem|der|den|your|the)\b",
    re.IGNORECASE,
)
#: A purpose of the sender's, struck out before :data:`_SENDER_ACTS` is read ("Damit wir Ihren Antrag bearbeiten
#: können, …", "Um … prüfen zu können, …", "Für die weitere Bearbeitung …", "… zur Prüfung") — never one with an
#: object of its own ("Die Frist für die Prüfung Ihres Antrags …").
_PURPOSE = re.compile(
    r"\bdamit\s+wir\b[^,.;:!?]{0,120}?\b(?:können|kann)\b|\bum\b[^,.;:!?]{0,120}?\bzu\s+können\b"
    r"|\b(?:zur|für\s+die)\s+(?:weitere[n]?\s+)?(?:prüfung|bearbeitung)\b(?!\s+(?:ihre[rs]?|des|der|von)\b)"
    r"|\bso\s+(?:that\s+)?we\s+can\b[^,.;:!?]{0,120}",
    re.IGNORECASE,
)
#: The sender's past act ("Wir haben der Gegenseite eine Frist bis … gesetzt", "Wir haben Sie mit Schreiben vom …
#: aufgefordert …").
_SENDER_DID = re.compile(
    r"\b(?:wir|we)\s+(?:haben|hatten|have|had)\b[^.;:!?]{0,120}?\b(?:gesetzt|eingeräumt|gewährt|aufgefordert|gebeten"
    r"|mitgeteilt|informiert|set|given|granted|asked|requested)\b",
    re.IGNORECASE,
)
#: Something done, paid or only stated ("… – das hat sich erledigt", "sie liegen uns inzwischen vor", "ist
#: eingegangen", "bezahlte Rechnungen", "gebucht", "hätten … vorliegen müssen", "ursprünglich", "Offene Posten", a
#: statement's "Kontoauszug", "Saldo", "Stand", "Vielen Dank für Ihre Zahlung", "to appear on your next statement",
#: "Your account is in credit", "per Dauerauftrag").
_DONE = re.compile(
    r"\berledigt\b|\binzwischen\b|\bliegen\s+uns\s+(?:\w+\s+){0,3}?vor\b|\bliegt\s+uns\s+(?:\w+\s+){0,3}?vor\b"
    r"|\b(?:ist|sind)\s+(?:\w+\s+){0,3}?eingegangen\b(?!\s+sein\b)|\beingegangen\s+(?:ist|sind)\b"
    r"|\bbezahlt\b(?!\s+(?:werden|sein)\b)|\bbezahlte[nmrs]?\b|\bgebucht\b|\bverbucht\b|\bhätten?\b"
    r"|\bursprünglich\w{0,3}|\boffene[nr]?\s+posten\b|\bkontoauszug\w{0,3}|\bkontostand\w{0,3}|\bsaldo\b|\bstand\b"
    r"|\bdank\s+für\s+ihre\s+(?:zahlung|überweisung)|\bthank\s+you\s+for\s+your\s+payment"
    r"|\bhas\s+been\s+(?:paid|received|settled)|\bin\s+credit\b|\bappear\s+on\s+your\b|\bstatement\s+(?:period|date)\b"
    r"|\b(?:next|this|monthly|annual)\s+statement\b|\bdauerauftrag\w{0,2}|\bstanding\s+order\b",
    re.IGNORECASE,
)
#: No demand: an offer, a survey, a contest or raffle, a tender, an agenda, an event, a donation ("Senden Sie uns den
#: Fragebogen … und erhalten Sie einen Gutschein", "Ihr Beitrag zum Fotowettbewerb", "Anträge zur Tagesordnung …",
#: "Abgabetermin für die Angebote der Handwerker", "Early-bird offer", "our short survey", "scholarship").
_NOT_A_DEMAND = re.compile(
    r"\b\w{0,20}(?:angebot\w{0,4}|umfrage\w{0,2}|befragung\w{0,2}|gutschein\w{0,2}|gewinnspiel\w{0,3}"
    r"|verlosung\w{0,2}|wettbewerb\w{0,3}|preisfrage\w{0,2}|preisausschreiben|ausschreibung\w{0,3}"
    r"|tagesordnung\w{0,3}|veranstaltung\w{0,3}|einladung\w{0,3}|feier\w{0,3}|fest(?:es|s)?|konzert\w{0,3}|seminar\w{0,3}"
    r"|kurs(?:e|es)?|tagung\w{0,2}|versammlung\w{0,3}|zeitung\w{0,2}|spende\w{0,2}|stipendi\w{0,4})\b"
    r"|\bteilnahme\w{0,2}|\bteilnehm\w{0,4}|\boffer\w{0,3}|early[\s-]?bird|frühbucher\w{0,4}|\bsurvey\w{0,2}"
    r"|\bvoucher\w{0,2}|\bcontest\w{0,2}|\bquiz\w{0,3}|\braffle\w{0,2}|\bprize\w{0,2}|\bgewinn(?:en|e|t)?\b"
    r"|\bwin(?:s|ner|ners|ning)?\b|\bentry\s+forms?\b|\bentries\b|\bnominat\w{0,5}|\btender\w{0,3}|\bagenda\b"
    r"|\bcourses?\b|\bworkshops?\b|\bevents?\b|\bconference\w{0,2}|\brsvp\b|\bdonation\w{0,2}"
    r"|scholarship\w{0,2}|newsletter\w{0,2}",
    re.IGNORECASE,
)
#: Holidays, opening and office hours ("Wichtiger Hinweis zu den Feiertagen: Überweisungen müssen bis 30.12. …,
#: damit sie noch im alten Jahr gebucht werden", "Öffnungszeiten der Kasse: Zahlbar bis 23.12.", "Betriebsferien").
_CLOSED = re.compile(
    r"\bfeiertag\w{0,3}|\bweihnacht\w{0,6}|\bjahreswechsel\w{0,2}|\bsilvester\b|\bneujahr\w{0,2}|\bostern\b"
    r"|\bgeschlossen\b|öffnungszeit\w{0,2}|sprechzeit\w{0,2}|sprechstunde\w{0,2}|\w{0,20}ferien\b|\burlaub\w{0,3}"
    r"|schließtag\w{0,2}|\bim\s+alten\s+jahr\b|\bholidays?\b|\bchristmas\b|\bnew\s+year\b|\bopening\s+(?:hours|times)\b"
    r"|\boffice\s+hours\b|\bclosed\b",
    re.IGNORECASE,
)
#: A condition or a case the person may not be in, beside those of :data:`_NOT_OWED` and :data:`_LOOSE_NOT_OWED`
#: ("Bei Bedarf …", "ggf.", "etwaige …", "Im Falle einer Nachforderung …", "Nur bei …", "In the event of …", "In case
#: of …", "Where applicable, …").
_LOOSE_CONDITION = re.compile(
    r"\bbei\s+bedarf\b|\bgegebenenfalls\b|\bggf\b|\betwaig\w{0,3}|\bfür\s+den\s+fall\b|\bim\s+\w{0,20}fall(?:e|s)?\b"
    r"|\bnur\s+(?:bei|für)\b|\bin\s+the\s+event\b|\bin\s+case\b|\bwhere\s+(?:applicable|relevant|necessary|appropriate)\b"
    r"|\bif\s+(?:applicable|necessary|relevant|required|needed)\b",
    re.IGNORECASE,
)
#: A sentence that opens with a condition's verb ("Ändert sich Ihr Einkommen, müssen …") or names a group the person
#: may not belong to ("Für Selbstständige …").
_VERB_FIRST = re.compile(
    r"\A\s*(?:Ändert|Ändern|Haben|Hat|Ist|Sind|Liegt|Liegen|Erhalten|Bekommen|Wird|Werden|Gibt|Kommt|Fällt|Entfällt"
    r"|Ergibt|Ergeben|Besteht|Bestehen|Benötigen|Brauchen|Wünschen|Möchten|Ziehen|Wechseln|Beziehen)\s+[^,.;:!?]{1,100},"
)
_GROUP_ONLY = re.compile(
    r"\A\s*für\s+(?:selbstständige|selbständige|freiberufler\w{0,2}|rentner\w{0,4}|studierende|studenten"
    r"|arbeitnehmer\w{0,4}|beamte\w?|eltern|mitglieder|neukunden|bestandskunden)\b",
    re.IGNORECASE,
)
#: Money or a document that comes to the person ("Das Geld sollte bis … bei Ihnen eingegangen sein", "Die Unterlagen
#: sollten Ihnen bis … vorliegen", "… an Sie zu überweisen", "auf Ihr Konto", "to you", "into your account", "reach
#: your bank", "send you", "refund", a benefit, a pension, "Kindergeld", "Guthaben"): no deadline of hers. "Sie", "Ihnen", "Ihr" are read as written (capitals: the
#: person; "ihr", "ihnen": others).
_TO_YOU = re.compile(
    r"\bbei\s+Ihnen\b|\bIhnen\s+(?:[\w-]+\s+){0,6}?(?:vorliegen|vorliegt|zugehen|zugeht|zugegangen|zukommen|zugestellt)\b"
    r"|\ban\s+Sie\s+(?:[\w-]+\s+){0,2}?(?:zu\s+)?(?i:überw|zahl|auszahl|erstatt|zurück|gesandt|gesendet|geschickt)\w*"
    r"|(?i:\w{0,20}(?:zahlung|überweisung|erstattung))\s+an\s+Sie\b"
    r"|(?i:\b(?:auf|an)\s+)Ihr(?:em|en)?\s+(?:[\w-]+\s+)?(?i:konto)\b|\bIhrem\s+(?:[\w-]+\s+)?(?i:konto\s+gutgeschrieben)"
    r"|(?i:\bto\s+you\b|\binto\s+your\s+(?:\w+\s+)?account\b|\bpaid\s+to\s+you\b|\bsend\s+you\b|\breach\s+your\s+bank\b"
    r"|\bcredited\s+to\s+your\b|\brefund\w{0,3}|\bbenefits?\b|\bpension\b|\bpayouts?\b|\breimburs\w{0,6}|\ballowance\b"
    r"|\b(?:kinder|wohn|eltern|bürger|arbeitslosen|kranken|pflege)geld\w{0,2}|\brenten?\b|\bguthaben\w{0,2})"
)
#: The person as the one asked to act, in the looser wording's own words ("Senden Sie", "Bitte gleichen Sie …
#: aus", "Bitte lassen Sie uns …", "Wir bitten Sie um …"), read as written: a capital "Sie" is the person, "sie" is
#: others ("… senden sie uns bis …": they). A possessive alone ("Ihre Zahlung", "Ihrer Versicherung", "your") never
#: names her as the one to act (2026-10-07 re-review).
_YOU_ACT = re.compile(r"\bSie\b")
#: Where the obligation goes: to the sender (money: a payment verb, "an uns", "bei uns", "auf unser Konto", "Ihre
#: Zahlung"; a
#: document: "uns", "zurück", "einreichen", "vorlegen", "abgeben"; English "to us", "reach us", "our account",
#: "return", "submit", "file", "received").
_TOWARD: dict[_Kind, re.Pattern[str]] = {
    "payment": re.compile(
        r"\b(?:(?:be|ein)?zahlen|einzuzahlen|überweisen|begleichen|entrichten|ausgleichen|auszugleichen|gleichen"
        r"|(?:be|ein)?gezahlt|bezahlt|überwiesen|beglichen|ausgeglichen|entrichtet|leisten|geleistet|abgeben|abgegeben)\b"
        r"|\b(?:an|bei)\s+uns\b|\bunser\w{0,2}\s+(?:[\w-]+\s+)?konto\b|\bhier\b"
        r"|\b(?:ihre?[nmr]?|your)\s+(?:[\w-]+\s+)?(?:zahlung|überweisung|payment|remittance)\b"
        r"|\b(?:pay|paid|settle[ds]?|remit\w{0,3}|transfer\w{0,3})\b|\bto\s+us\b|\breach(?:es)?\s+us\b"
        r"|\bour\s+(?:\w+\s+)?account\b|\breceived\b|\bcredited\b",
        re.IGNORECASE,
    ),
    "declaration": re.compile(
        r"\buns\b|\bhier\b|\bzurück\w*|\beinreich\w*|\beingereicht\b|\beinzureichen\b|\bvorleg\w*|\bvorgelegt\b"
        r"|\bvorzulegen\b|\bnachreich\w*|\bnachgereicht\b|\bnachzureichen\b|\beinsend\w*|\beingesandt\b|\beingesendet\b"
        r"|\beinzusenden\b|\babgeb\w*|\babgegeben\b|\babzugeben\b|\brücksend\w*|\brückgabe\w*|\babgabe\b"
        r"|\bus\b|\bour\s+(?:office|address|team|department)\b|\breturn\w{0,3}|\bsubmit\w{0,4}|\bfil(?:e|ed|ing)\b"
        r"|\blodge[ds]?\b|\breceived\b|\barrive\b|\breach(?:es)?\s+us\b",
        re.IGNORECASE,
    ),
}
#: A letter that says nothing needs doing ("Sie müssen nichts weiter tun", "kein Handlungsbedarf", "You do not need to
#: do anything"): no date on its page is filed in looser words.
_NOTHING_TO_DO = re.compile(
    r"\bsie\s+müssen\s+nichts\b|\bnichts\s+(?:weiter\s+)?(?:zu\s+)?(?:tun|unternehmen|veranlassen)\b"
    r"|\bkein(?:en)?\s+handlungsbedarf\b|\byou\s+(?:do\s+not|don't)\s+need\s+to\s+do\s+anything\b"
    r"|\bno\s+(?:further\s+)?action\s+(?:is\s+)?(?:needed|required)\b",
    re.IGNORECASE,
)
#: A statement's or a status letter's words ("Kontoauszug", "Stand:", "Sachstand", "Eingangsbestätigung", "Status:",
#: "statement"): no label on its page is the person's deadline.
_STATUS = re.compile(
    r"\bsachstand\w{0,2}|\bbearbeitungsstand\w{0,2}|\bzwischennachricht\w{0,2}|\bzwischenbescheid\w{0,2}"
    r"|\beingangsbestätigung\w{0,2}|\bstatus\s*:|\bkontoauszug\w{0,3}|\bkontostand\w{0,3}|\bstand\s*:"
    r"|\bstatement\b|\baccount\s+summary\b|\bstatus\s+update\b|\bvollständig\s+(?:vor|eingegangen)\b"
    r"|\b(?:documents|paperwork|application)\s+(?:is|are)\s+(?:now\s+)?complete\b",
    re.IGNORECASE,
)
#: The person asked to pay or to send something elsewhere on the page ("Bitte überweisen Sie den Betrag …", "Senden
#: Sie uns …", "please pay", "you must return …"): what makes a label ("Zahlungsfrist: …") hers.
_PAGE_ASKS: dict[_Kind, re.Pattern[str]] = {
    "payment": re.compile(
        r"(?i:\b(?:überweisen|zahlen|bezahlen|begleichen|entrichten|gleichen))\s+Sie\b"
        r"|(?i:\bbitte\s+(?:[\w-]+\s+){0,6}?(?:überweisen|zahlen|bezahlen|begleichen|entrichten)\b)"
        r"|(?i:\b(?:please|kindly)\s+(?:pay|settle|transfer|remit|make\s+(?:a\s+|the\s+)?payment)\b)"
        r"|(?i:\byou\s+(?:must|should|need\s+to|have\s+to|are\s+(?:required|asked)\s+to)\s+(?:pay|settle)\b)"
    ),
    "declaration": re.compile(
        r"(?i:\b(?:reichen|senden|schicken|legen|übersenden|übermitteln|füllen|unterschreiben))\s+Sie\b"
        r"|(?i:\bbitte\s+(?:[\w-]+\s+){0,6}?(?:einreichen|zurücksenden|zurückschicken|senden|schicken|vorlegen"
        r"|nachreichen|ausfüllen|unterschreiben)\b)"
        r"|(?i:\b(?:please|kindly)\s+(?:send|return|submit|complete|sign|provide|fill\s+in)\b)"
        r"|(?i:\byou\s+(?:must|should|need\s+to|have\s+to|are\s+(?:required|asked)\s+to)\s+"
        r"(?:send|return|submit|provide|file|complete)\b)"
    ),
}

# -- the looser wordings ----------------------------------------------------------------------------------------------

#: A date set as a deadline in looser words: "bis (zum | spätestens …)" as in :data:`_BY`, or "spätestens (am |
#: zum)", right before it.
_BY_LATEST = rf"(?:{_BY}|\bspätestens\s+(?:(?:am|zum)\s+)?{_WEEKDAY_WORD}(?:den\s+)?$)"
_BY_EN = (
    rf"\b(?:by|before|no\s+later\s+than|not\s+later\s+than|on\s+or\s+before)\s+(?:the\s+)?{_WEEKDAY_WORD}$"
)
#: The words of a sentence between a request and its date (as in :data:`_PAY_YOU`); within one clause, past no comma
#: but an amount's ("687,15 €").
_GAP = r"(?:[^.;:!?]|\.(?=\d)){0,120}?"
#: What is asked for, as a noun ("Zahlung", "Rücksendung", "Rückantwort", "Stellungnahme").
_ACT = (
    r"\w{0,30}(?:zahlung|überweisung|ausgleich|begleichung|rücksendung|zusendung|übersendung|einsendung|rückgabe"
    r"|abgabe|vorlage|einreichung|nachreichung|rückmeldung|antwort|stellungnahme|mitteilung|nachricht)\w{0,30}"
)
#: A field's start: a line's, or after a separator ("… · Zahlung bis: …", "Offener Betrag … – Frist: …").
_FIELD = r"(?:^|\n|[·|]|\s[–—-]\s)\s*"
_PAY_INFINITIVE = r"(?:(?:be|ein)?zahlen|überweisen|begleichen|entrichten|ausgleichen)"
_SEND_INFINITIVE = (
    r"(?:zurück(?:senden|schicken|geben)|einreichen|einsenden|vorlegen|nachreichen|zusenden|senden|schicken"
    r"|übersenden|übermitteln|mitteilen)"
)
#: A word between "Bitte bis …" and its infinitive that makes the date another act's than the infinitive's: a wait, a
#: later step or a negation ("Bitte bis zum … abwarten und erst danach überweisen", "… warten und dann überweisen",
#: "Bitte bis zum … nichts überweisen": 2026-10-07 re-review) — never a second act of the person's ("Bitte bis … ausgefüllt
#: und unterschrieben zurücksenden").
_NOT_THE_ACT = r"(?:\w*warten|dann|danach|anschließend|erst|nicht|nichts|kein\w*|nie)"
_LATEST = re.compile(_BY_LATEST, re.IGNORECASE)
#: What may stand before a sentence-shaped or imperative wording in its own sentence: nothing but "Bitte", "Please"
#: or "Kindly" (and a list's bullet). Anything else may be a condition or a group no list names ("Bei Nichtgefallen
#: …", "Sobald Sie umziehen, …", "When moving out, …", "For self-employed members, …": 2026-10-07 re-review), so such
#: a sentence files nothing.
_OPENS = re.compile(r"\s*(?:[•·*–—-]\s*)?(?:(?:bitte|please|kindly)\b[\s,]*)?", re.IGNORECASE)

#: How a looser wording makes its date the person's (:func:`_looser_dates`). Since the re-review of 2026-10-07 only
#: when its own words ask her, never by a possessive alone ("Ihre", "your") nor beside a word a list must name:
#: ``"sentence"`` when they name her as the one to act ("Senden Sie …", "Bitte gleichen Sie … aus", "Bitte lassen Sie
#: uns … zukommen": :data:`_YOU_ACT`) and the obligation goes to the sender (:data:`_TOWARD`); ``"asker"`` when the
#: sender asks her by name ("Wir bitten Sie um Zahlung …"); ``"imperative"`` when they ask her by their mood ("Bitte
#: bis … überweisen", "Kindly pay …", "Please ensure …") and the obligation goes to the sender — these three only at
#: their sentence's start (:data:`_OPENS`); ``"label"`` for a label line ("Zahlungsfrist: …", "Zahlungseingang bis:
#: …", "Einsendeschluss: …") with nothing after its date on its line but a field's separator, and ``"labelled"`` for
#: a labelled sentence ("Zahlung erbeten bis …", "Abgabetermin ist der …"), both only when the page asks her for that
#: kind elsewhere (:data:`_PAGE_ASKS`, or a strict date) and is no holiday, opening hours, offer, event, statement or
#: status letter.
_Shape = Literal["sentence", "asker", "imperative", "label", "labelled"]
#: The shapes that ask the person in their own words, and so must open their sentence (:data:`_OPENS`).
_ASKING: frozenset[_Shape] = frozenset({"sentence", "asker", "imperative"})
#: What may follow a label's date on its line: nothing, a full stop, or a field's separator ("Zahlungseingang bis:
#: 15.11.2026 | 120,00 €", "Frist: 30.10.2026 (Eingang bei uns)") — never more words, which may make the date a
#: window's first day ("Zahlungsfrist: 01.11.2026 bis spätestens 15.11.2026", "… bis Monatsende", "… zzgl. 14 Tage",
#: "1 November 2026 up to 15 November 2026": 2026-10-07 re-review).
_LABEL_ENDS = re.compile(r"[^\S\n]*[.;,]?[^\S\n]*(?:\n|$|[(|·])")


class _Family(NamedTuple):
    """A looser wording: ``before`` must end right before the date, ``after`` (when given) match the words after it;
    ``kind`` when the wording itself tells what is asked ("Bitte gleichen Sie … aus": a payment)."""

    name: str
    shape: _Shape
    before: re.Pattern[str]
    after: re.Pattern[str] | None = None
    kind: _Kind | None = None


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


#: A deadline's day named ("Abgabetermin", "Einsendeschluss", "Letzter Zahlungstag", "Letzter Tag für die Zahlung",
#: "Rückgabetermin für den Antrag").
_TERMIN = (
    r"(?:^|[\s(·|–—-])(?:(?:abgabe|rückgabe|einsende|einreichungs|vorlage)(?:termin|schluss)"
    r"|letzte[rn]?\s+(?:(?:zahlungs|überweisungs|abgabe|einsende|einreichungs|rückgabe)tag"
    r"|tag\s+(?:für|zur|zum)\s+(?:die\s+|den\s+|das\s+|ihre[nmrs]?\s+)?[\w-]+))"
    r"(?:\s+(?:für|zur|zum)\s+(?:die\s+|den\s+|das\s+|ihre[nmrs]?\s+)?(?:[\w-]+\s+){0,2}?[\w-]+)?"
)


#: The looser wordings kept after the re-review of 2026-10-07. Dropped there, each for a confirmed false alarm or a
#: wrong date of its own (ADR 0015): "Wir erwarten / benötigen / erbitten …", "Bis … erwarten wir …", "Wir bitten um
#: … Ihres …" (a possessive alone), "… wird bis … erwartet", "… muss bis … bei uns eingegangen sein / vorliegen /
#: bezahlt werden", "… ist bis … auszugleichen", "Ihre Zahlungsfrist endet am …", "setzen wir Ihnen eine Frist bis …",
#: "… wird eine Frist bis … gesetzt", "must be received / paid by", "you must pay … by", "we need / expect / must
#: receive …", "we look forward to receiving …", "we kindly request …", "… is expected by …", "The deadline for … is
#: …"; and every date without its year.
_LOOSE: tuple[_Family, ...] = (
    # "Wir bitten Sie um Zahlung bis zum", "Wir bitten Sie höflich um Ausgleich des Rechnungsbetrags bis"
    _Family(
        "wir_bitten_um",
        "asker",
        _rx(
            rf"\b(?:wir\s+bitten|bitten\s+wir)\s+sie\s+(?:\w+\s+)?um\s+(?:[\w-]+\s+){{0,2}}?{_ACT}\b{_GAP}{_BY_LATEST}"
        ),
    ),
    # "Zahlung erbeten bis", "Rückantwort erbeten bis Freitag,"
    _Family("erbeten", "labelled", _rx(rf"\b{_ACT}\s+erbeten\s+{_BY}")),
    # "Senden Sie uns die Unterlagen bis zum" (a whole verb: "senden", "schicken" need no particle after the date)
    _Family("senden_sie", "sentence", _rx(rf"\b(?:senden|schicken)\s+sie\b{_GAP}{_BY}")),
    # "Zahlungsfrist:", "Abgabefrist:", "Frist für die Zahlung:", "Unterlagen nachreichen – Frist:"
    _Family(
        "frist_label",
        "label",
        _rx(
            rf"(?:^|[\s(·|–—-])(?:{_DUE_FRIST}|frist(?:\s+(?:für|zur|zum)\s+(?:[\w-]+\s+){{0,2}}?[\w-]+)?)\s*:\s*"
            rf"{_WEEKDAY_WORD}$"
        ),
    ),
    # "Abgabetermin:", "Letzter Zahlungstag:"; "Einsendeschluss ist der", "Letzter Tag für die Zahlung ist der"
    _Family("termin_label", "label", _rx(rf"{_TERMIN}\s*:\s*{_WEEKDAY_WORD}(?:den\s+)?$")),
    _Family("termin_ist", "labelled", _rx(rf"{_TERMIN}\s+ist\s+(?:der|am)\s*{_WEEKDAY_WORD}(?:den\s+)?$")),
    # a field "Zahlungseingang (bei uns) bis:", "Eingang der Unterlagen bei uns bis", "Zahlung bis:", "Vorlage bis"
    _Family(
        "field_bis",
        "label",
        _rx(
            rf"{_FIELD}(?:zahlungseingang(?:\s+bei\s+uns)?|eingang\s+(?:der|des|ihrer|ihres)\s+[\w-]+(?:\s+bei\s+uns)?"
            r"|(?:zahlung|überweisung|abgabe|rücksendung|rückgabe|vorlage|einreichung|einsendung|nachreichung)"
            r"(?:\s+(?:der|des|ihrer|ihres)\s+[\w-]+)?)"
            rf"\s+bis(?:\s+(?:zum|spätestens))?\s*:?\s*{_WEEKDAY_WORD}(?:den\s+)?$"
        ),
    ),
    # English: "Kindly pay the outstanding amount by", "Please make payment by"
    _Family(
        "en_kindly",
        "imperative",
        _rx(
            r"\b(?:kindly|please\s+(?:make|arrange))\s+(?:pay|settle|return|submit|send|payment|the\s+payment)\b"
            rf"{_GAP}{_BY_EN}"
        ),
    ),
    # "Please ensure that your payment reaches us by"
    _Family("en_ensure", "imperative", _rx(rf"\bplease\s+(?:ensure|make\s+sure)\b{_GAP}{_BY_EN}")),
    # "Payment deadline:", "Last day to pay:", "Reply by:"
    _Family(
        "en_label",
        "label",
        _rx(
            rf"{_FIELD}(?:(?:payment|submission|return|reply)\s+deadline|deadline(?:\s+for\s+(?:[\w-]+\s+){{0,2}}?[\w-]+)?"
            rf"|last\s+day\s+(?:to|for)\s+[\w-]+|(?:reply|respond|return)\s+by)\s*:\s*{_WEEKDAY_WORD}$"
        ),
    ),
    # the words after the date complete these:
    # "Um Zahlung bis zum … wird gebeten.", "Überweisung bis spätestens … erbeten."
    _Family(
        "wird_gebeten", "labelled", _LATEST, _rx(r"^\s*(?:[^\s.;:!?,]+\s+){0,3}?(?:erbeten|wird\s+gebeten)\b")
    ),
    # "Bitte bis zum … überweisen.", "Bitte bis 23.10.2026 unterschrieben zurücksenden."
    _Family(
        "bitte_infinitiv",
        "imperative",
        _rx(rf"\bbitte\s+{_BY}"),
        _rx(
            rf"^\s*(?:(?!{_NOT_THE_ACT}\b)[^\s.;:!?,]+\s+){{0,5}}?(?:{_PAY_INFINITIVE}|{_SEND_INFINITIVE}|abgeben)\b"
        ),
    ),
    # "Bitte gleichen Sie den offenen Betrag bis zum … aus."
    _Family(
        "gleichen_sie_aus",
        "sentence",
        _rx(rf"\bgleichen\s+sie\b{_GAP}{_BY}"),
        _rx(r"^\s*(?:[^\s.;:!?,]+\s+){0,3}?aus\b"),
        kind="payment",
    ),
    # "Bitte lassen Sie uns die fehlenden Belege bis zum … zukommen."
    _Family(
        "lassen_sie_zukommen",
        "sentence",
        _rx(rf"\blassen\s+sie\b{_GAP}{_BY}"),
        _rx(r"^\s*(?:[^\s.;:!?,]+\s+){0,3}?zukommen\b"),
    ),
)


class _Matched(NamedTuple):
    family: _Family
    words: str  # the words that set the date, before and after it
    start: int  # where they start in the words before the date


def _loose_family(before: str, after: str) -> _Matched | None:
    """The looser wording (:data:`_LOOSE`) that sets the date between ``before`` and ``after``, if any: the first."""
    for family in _LOOSE:
        found = family.before.search(before)
        if found is None:
            continue
        if family.after is None:
            return _Matched(family, found.group(), found.start())
        completed = family.after.match(after)
        if completed is None:
            continue
        return _Matched(family, f"{found.group()} {completed.group()}", found.start())
    return None


# -- what is asked: a payment or a declaration ------------------------------------------------------------------------

#: The verb that tells what is asked ("… zu überweisen", "… bezahlt werden", "must be paid": a payment; "…
#: zurücksenden", "… eingereicht werden", "must be filed": a declaration; "abgeben", "erfolgen", "eingehen",
#: "received" tell neither).
_PAYS_VERB = re.compile(
    rf"\b(?:zu\s+)?{_PAY_INFINITIVE}\b|\b(?:auszugleichen|einzuzahlen|gleichen)\b"
    r"|\b(?:bezahlt|gezahlt|eingezahlt|überwiesen|beglichen|ausgeglichen|entrichtet)\s+(?:werden|sein)\b"
    r"|\b(?:pay|paid|settle|settled|transfer|transferred|credited)\b",
    re.IGNORECASE,
)
_SENDS_VERB = re.compile(
    rf"\b(?:zu\s+)?{_SEND_INFINITIVE}\b|\b(?:einzureichen|einzusenden|vorzulegen|zurückzusenden|zurückzuschicken"
    r"|zurückzugeben|nachzureichen|zuzusenden|mitzuteilen)\b"
    r"|\b(?:eingereicht|vorgelegt|zurückgegeben|zurückgesandt|zurückgesendet|zurückgeschickt|eingesandt|eingesendet"
    r"|übersandt|übermittelt|nachgereicht)\s+(?:werden|sein)\b"
    r"|\b(?:submit|submitted|return|returned|file|filed|lodge|lodged|send|sent|provide|provided)\b",
    re.IGNORECASE,
)


def _verb_kind(words: str) -> _Kind | None:
    """What the verbs of ``words`` ask for: one kind only, else ``None``."""
    pays, sends = _PAYS_VERB.search(words) is not None, _SENDS_VERB.search(words) is not None
    return "payment" if pays and not sends else "declaration" if sends and not pays else None


#: A label's own word ("Zahlungsfrist", "Letzter Zahlungstag", "Payment deadline": a payment; "Abgabefrist",
#: "Rücksendung bis", "Einsendeschluss", "Reply by": a declaration).
_LABEL_PAYS = re.compile(r"\b(?:zahlungs?|überweisungs?)\w*|\bpay\w*", re.IGNORECASE)
#: A label's word that names a payment whole ("Zahlungsfrist", "Letzter Zahlungstag", "Zahlungseingang", "Payment
#: deadline", "Last day to pay") — never a compound whose last word names something else ("Zahlungsbestätigung",
#: "Zahlungsnachweis", "payment confirmation": 2026-10-07 re-review).
_LABEL_PAYS_WHOLE = re.compile(
    r"\b(?:zahlungs?|überweisungs?)(?:frist|termin|tag|ziel|eingang)?\b|\bpay\b|\bpayment\b(?!\s+(?!deadline\b)\w)",
    re.IGNORECASE,
)
_LABEL_SENDS = re.compile(
    r"\b(?:abgabe|rücksend|rückgabe|vorlage|einreich|einsend|nachreich|rückantwort|antwort|rückmeld)\w*"
    r"|\b(?:return|reply|submission|response|respond)\w*",
    re.IGNORECASE,
)

#: Nouns naming money, and the last word of a compound that does ("Rechnungsbetrag", "Kaltmiete", "Antragsgebühr"):
#: whole words only — "Vermieter" names no rent.
_PAY_HEADS = frozenset(
    {
        "zahlung", "zahlungen", "überweisung", "überweisungen", "betrag", "betrags", "beträge", "beträgen", "gebühr",
        "gebühren", "rückstand", "rückstands", "rückstände", "rückständen", "forderung", "forderungen",
        "begleichung", "kosten", "summe", "summen", "miete", "mieten", "entgelt", "entgelts", "entgelte", "steuer",
        "steuern", "rechnung", "rechnungen", "kaution", "prämie", "prämien", "abschlag", "abschlags", "abschläge",
        "rate", "raten", "zinsen", "zuschlag", "zuschläge", "ausgleich", "ausgleichs", "zahlungseingang",
    }
)  # fmt: skip
#: "Beitrag" names money only beside an amount or a payment's verb ("Den Kostenbeitrag von 35 € …"; "Ihr Beitrag zur
#: Mieterzeitung" is an article).
_WEAK_PAY_HEADS = frozenset({"beitrag", "beitrags", "beiträge", "beiträgen"})
#: Nouns naming a document or an answer, and the last word of a compound that does ("Nebenkostenabrechnung",
#: "Steuerbescheid", "Zahlungsnachweis", "Mietbescheinigung").
_SEND_HEADS = frozenset(
    {
        "unterlage", "unterlagen", "erklärung", "erklärungen", "nachweis", "nachweise", "nachweises", "nachweisen",
        "bescheinigung", "bescheinigungen", "formular", "formulare", "formulars", "bogen", "bögen", "zettel",
        "abschnitt", "abschnitts", "bericht", "berichts", "berichte", "antrag", "antrags", "anträge", "beleg",
        "belege", "belegs", "stellungnahme", "rückmeldung", "antwort", "vertrag", "vertrags", "verträge",
        "unterschrift", "unterschriften", "auszug", "auszugs", "auszüge", "dokument", "dokumente", "dokuments",
        "kopie", "kopien", "rücksendung", "rückgabe", "abgabe", "einreichung", "vorlage", "nachreichung",
        "einsendung", "zusendung", "übersendung", "nachricht", "mitteilung", "angaben", "auskunft", "auskünfte",
        "bescheid", "bescheids", "bescheide", "abrechnung", "abrechnungen", "aufstellung", "quittung", "quittungen",
        "vollmacht", "ausweis", "ausweises", "attest",
    }
)  # fmt: skip
#: English words and money signs, whole only.
_PAY_WORDS = frozenset(
    {
        "€", "£", "$", "eur", "euro", "geld", "gelder", "payment", "payments", "pay", "paid", "balance", "fee",
        "fees", "amount", "amounts", "invoice", "invoices", "bill", "bills", "rent", "premium", "premiums", "charge",
        "charges", "arrears", "instalment", "instalments", "installment", "installments", "sum", "money", "debt",
        "deposit",
    }
)  # fmt: skip
_SEND_WORDS = frozenset(
    {
        "document", "documents", "form", "forms", "reply", "response", "evidence", "return", "returns",
        "questionnaire", "agreement", "contract", "signature", "declaration", "application", "paperwork",
        "information", "details", "proof", "certificate", "certificates", "slip", "submission", "payslip", "payslips",
        "statement", "statements", "receipt", "receipts",
    }
)  # fmt: skip
_NOUNS: dict[str, tuple[_Kind, bool]] = {
    **dict.fromkeys(_PAY_HEADS, ("payment", False)),
    **dict.fromkeys(_WEAK_PAY_HEADS, ("payment", True)),
    **dict.fromkeys(_SEND_HEADS, ("declaration", False)),
}
_WORDS: dict[str, tuple[_Kind, bool]] = {
    **_NOUNS,
    **dict.fromkeys(_PAY_WORDS, ("payment", False)),
    **dict.fromkeys(_SEND_WORDS, ("declaration", False)),
}
#: A word, a hyphenated compound ("Steuer-ID", "Kfz-Steuer") or a money sign.
_TOKEN = re.compile(r"[€£$]|\w+(?:-\w+)*")
#: Heads that name money only as whole words: "Inserate", "accurate", "separate" end in "rate" but name no Rate.
_WHOLE_ONLY = frozenset({"rate", "raten"})
#: An amount beside "Beitrag" ("35 €", "120,00 EUR").
_AMOUNTISH = re.compile(r"[€£$]|\d,\d{2}\b|\b(?:eur|euro)\b", re.IGNORECASE)
#: "X über / für / zu / of Y": X is what is asked ("Nachweis über die Zahlung", "Gebühr für den Antrag", "proof of
#: payment").
_HEAD_OF = re.compile(
    r"\s+(?:über|für|zur|zum|zu|von|of|for|on)\s+(?:(?:den|die|das|der|des|dem|ihre[nmrs]?|ihr|the|your|a|an)\s+)?"
    r"(?:[\w-]+\s+){0,2}",
    re.IGNORECASE,
)


def _noun_kind(word: str) -> tuple[_Kind, bool] | None:
    """What a word names (:data:`_PAY_HEADS`, :data:`_SEND_HEADS`, :data:`_PAY_WORDS`, :data:`_SEND_WORDS`) — a
    compound by its last word, the longest that is one ("Nebenkostenabrechnung": an Abrechnung, not a Rechnung; never
    "rate" inside a word, :data:`_WHOLE_ONLY`) —, and whether only weakly ("Beitrag")."""
    folded = word.casefold()
    known = _WORDS.get(folded)
    if known is not None:
        return known
    for cut in range(3, len(folded) - 2):
        head = _NOUNS.get(folded[cut:])
        if head is not None:
            return None if folded[cut:] in _WHOLE_ONLY else head
    return None


def _nouns_kind(text: str) -> _Kind | None:
    """What the nouns of ``text`` ask for: their one kind, or — both named — the first's when the other only says
    what it is about (:data:`_HEAD_OF`); else ``None`` (unclear: no to-do). A hyphenated compound counts by its last
    part; one whose earlier part names a kind its last part does not ("Steuer-ID", "Gebühren-Übersicht") leaves the
    text unclear."""
    strong = _AMOUNTISH.search(text) is not None or _PAYS_VERB.search(text) is not None
    nouns: list[tuple[int, int, _Kind]] = []
    for found in _TOKEN.finditer(text):
        *parts, last = found.group().split("-")
        named = _noun_kind(last)
        if any(
            (part_named := _noun_kind(part)) is not None and (named is None or part_named[0] != named[0])
            for part in parts
        ):
            return None
        if named is not None and (strong or not named[1]):
            nouns.append((found.start(), found.end(), named[0]))
    kinds = {kind for _start, _end, kind in nouns}
    if len(kinds) == 1:
        return kinds.pop()
    if not kinds:
        return None
    first = nouns[0]
    other = next(noun for noun in nouns if noun[2] != first[2])
    return first[2] if _HEAD_OF.fullmatch(text, first[1], other[0]) else None


def _label_kind(words: str, line: str) -> _Kind | None:
    """What a label asks for: the verb on its line ("Unterlagen nachreichen – Frist:"), its own word ("Zahlungsfrist",
    "Rücksendung bis") unless its own nouns name the other kind ("Frist für den Zahlungsnachweis", "Deadline for proof
    of payment": unclear) or a payment's word is only a compound's first part ("Frist für die Zahlungsbestätigung":
    unclear), else the nouns on its line before the date ("Offener Betrag 136,00 € – Frist:")."""
    told = _verb_kind(line)
    if told is not None:
        return told
    pays, sends = _LABEL_PAYS.search(words) is not None, _LABEL_SENDS.search(words) is not None
    if pays != sends:
        kind: _Kind = "payment" if pays else "declaration"
        named = _nouns_kind(words)
        if named not in (None, kind) or (pays and named is None and not _LABEL_PAYS_WHOLE.search(words)):
            return None
        return kind
    return _nouns_kind(line)


#: A window's first date ("vom 01.11. bis 15.11.", "Zahlungsfrist: 01.11.2026 – 15.11.2026", "1 November to 15
#: November"): never a deadline.
_RANGE_START = re.compile(
    rf"^\s*(?:bis(?:\s+(?:zum|einschließlich))?|und(?:\s+dem)?|–|—|-|to|until|till|through|thru|and)\s*"
    rf"{_WEEKDAY_WORD}(?:den\s+)?$",
    re.IGNORECASE,
)
#: A greeting's line ("Sehr geehrte Frau Probe,", "Dear Ms Probe,"): the letterhead and the address before it are no
#: words of the sentence after it.
_SALUTATION_LINE = re.compile(rf"^[^\S\n]*{_SALUTATION.pattern}[^\n]*", re.IGNORECASE | re.MULTILINE)


def _offers_option(asked: str) -> bool:
    """Whether the sentence before a request offers an option (:data:`_OPTION_ASKED`, never a W-question): the strict
    path's reading, done on the words after its last but one question mark — the only ones a match can stand in — so
    it stays linear on long untrusted text."""
    asked = asked.strip()
    if not asked.endswith("?"):
        return False
    question = asked[asked.rfind("?", 0, len(asked) - 1) + 1 :]
    return _OPTION_ASKED.search(question) is not None and not _W_QUESTION.match(asked)


class _Region:
    """A date's own sentence on the looser path — its clause, cut at a greeting's line (the header above "Sehr geehrte
    …" is a sentence of its own) — and what its words say, each read once."""

    def __init__(self, text: str, sender: frozenset[str]) -> None:
        self.text = text
        self._sender = sender
        self._cache: dict[str, bool] = {}

    def _third_party(self) -> bool:
        for found in _THIRD_PARTY.finditer(self.text):
            words = {word.casefold() for word in re.findall(r"\w+", found.group())}
            if not words & self._sender:
                return True
        return False

    @property
    def guarded(self) -> bool:
        """Its words keep its dates from being the person's on the looser path."""
        if "guarded" not in self._cache:
            text = self.text
            self._cache["guarded"] = bool(
                _NOT_OWED.search(text)
                or _LOOSE_NOT_OWED.search(text)
                or _LOOSE_CONDITION.search(text)
                or _VERB_FIRST.match(text)
                or _GROUP_ONLY.match(text)
                or _SENDER_ACTS.search(_PURPOSE.sub(" ", text))
                or _SENDER_DID.search(text)
                or _DONE.search(text)
                or _NOT_A_DEMAND.search(text)
                or _CLOSED.search(text)
                or _TO_YOU.search(text)
                or self._third_party()
            )
        return self._cache["guarded"]

    def toward(self, kind: _Kind) -> bool:
        key = f"toward-{kind}"
        if key not in self._cache:
            self._cache[key] = _TOWARD[kind].search(self.text) is not None
        return self._cache[key]


class _Found(NamedTuple):
    """A date a to-do of code's is filed for, and where the letter sets it (its quote's: :func:`_deadline_item`)."""

    day: date
    kind: _Kind
    clause: str
    lo: int
    hi: int
    previous: int
    strict: bool  # set in strict words: its line is its quote when they stand on it


def _sets_strictly(before: str, after: str) -> bool:
    return _deadline_kind(before, after) is not None


def _sets_loosely(before: str, after: str) -> bool:
    return _deadline_kind(before, after) is not None or _loose_family(before, after) is not None


def _reading_kinds(extraction: DocumentExtraction) -> set[_Kind]:
    """The kinds of the reading's dated to-dos (a payment's; a declaration's): a date in looser words of that kind is
    likelier the same obligation's second date than one the reading left out."""
    kinds: set[_Kind] = set()
    for item in extraction.items:
        if item.date.type == "none":
            continue
        if item.kind == "payment" or item.date.nature == "payment":
            kinds.add("payment")
        elif item.date.nature == "declaration":
            kinds.add("declaration")
    return kinds


def _page_asks(clauses: Sequence[str]) -> set[_Kind]:
    """What the page asks the person for in a sentence of its own (:data:`_PAGE_ASKS`), never in a condition, an
    option or a negation."""
    asks: set[_Kind] = set()
    for clause in clauses:
        for kind, pattern in _PAGE_ASKS.items():
            if (
                kind not in asks
                and pattern.search(clause)
                and not _NOT_OWED.search(clause)
                and not _LOOSE_NOT_OWED.search(clause)
            ):
                asks.add(kind)
    return asks


def _looser_dates(
    extraction: DocumentExtraction,
    pages: Sequence[PageInput],
    *,
    start: date | None,
    today: date | None,
    taken: Sequence[date],
    series: set[date],
    paying: bool,
    by_label_only: bool,
) -> list[_Found]:
    """The dates the looser path files (ADR 0015, 2026-10-07, narrowed by its re-review): a date with its year in a
    looser wording (:data:`_LOOSE`) — at most one per kind, the earliest, and only for a kind that neither a dated
    to-do of the reading (:func:`_reading_kinds`) nor a strict date of the letter still to come covers (two dates for
    one obligation: the reading's or the strict one stands). A date without its year files nothing, here as on the
    strict path.

    None on a page that says nothing needs doing (:data:`_NOTHING_TO_DO`), nor as a window's first date
    (:data:`_RANGE_START`). A wording that asks the person in its own words (:data:`_ASKING`: "Senden Sie uns …",
    "Bitte gleichen Sie … aus", "Wir bitten Sie um Zahlung …", "Bitte bis … überweisen", "Kindly pay …") files only at
    its sentence's start (:data:`_OPENS`), with the obligation going to the sender where its shape needs it
    (:data:`_TOWARD`); a label ("Zahlungsfrist: …") or a labelled sentence ("Zahlung erbeten bis …") only on a page
    that asks her for its kind and is no holiday, opening hours, offer, event, statement or status letter, a label
    only with nothing but a separator after its date (:data:`_LABEL_ENDS`). Never when a word of the sentence guards it
    (:attr:`_Region.guarded`: a negation, a condition, an option, a third party, the sender's own act, money or papers
    that come to her, something done or stated, an offer, survey, contest, tender or event, a holiday or opening
    hours), nor when its kind is unclear — the verb's, else the nouns' (:func:`_nouns_kind`), never when the two
    disagree ("Senden Sie uns den Betrag"). None when a reading's warning doubts the letter's money
    (:data:`_PAY_DOUBT`); every payment goes through the gates of the strict path (``by_label_only``: a debit, a paid
    letter, a payout, :func:`_not_owed_by_label`, read once for both paths; an instalment of the reading's; a full
    price)."""
    if any(_PAY_DOUBT.search(warning) for warning in extraction.warnings):
        return []
    covered = _reading_kinds(extraction)
    quoted = {
        day
        for item in extraction.items
        for _start, _end, mention in date_spans(fold_punctuation(item.quote or ""))
        if (day := mention.as_date()) is not None
    }
    sender = frozenset(
        word.casefold() for word in re.findall(r"\w+", extraction.sender.name if extraction.sender else "")
    )
    earliest: dict[_Kind, _Found] = {}

    def consider(found: _Found) -> None:
        if found.kind not in earliest or found.day < earliest[found.kind].day:
            earliest[found.kind] = found

    for page in pages:
        clauses = sentences(_visible(page))
        flat = "".join(clauses)
        # the page says nothing needs doing: no date on it is the looser path's; it speaks of holidays or opening hours:
        # no label on it
        nothing = _NOTHING_TO_DO.search(flat) is not None
        closed = _CLOSED.search(flat) is not None
        hits: set[_Kind] = set()  # the kinds the page sets in strict words, in a sentence of no guard
        labels: list[_Found] = []  # labels' dates: the person's when the page asks her for their kind
        for at, clause in enumerate(clauses):
            spans = date_spans(clause)
            if not spans or _REMEDY.search(clause):
                continue
            if at > 0 and _offers_option(clauses[at - 1]):
                continue  # "Sie möchten Ihren Vertrag nicht verlängern? Dann senden Sie …": an option's request
            readings = Counter((lo, hi) for lo, hi, _mention in spans)  # an ambiguous slash date reads twice
            # greetings' lines, found once per sentence; each date's own region is read between them by bisection
            greeting_starts: list[int] = []
            greeting_ends: list[int] = []
            for greeting in _SALUTATION_LINE.finditer(clause):
                greeting_starts.append(greeting.start())
                greeting_ends.append(greeting.end())
            regions: dict[tuple[int, int], _Region] = {}
            strict_guarded: bool | None = None
            for index, (lo, hi, mention) in enumerate(spans):
                if mention.ambiguous or readings[(lo, hi)] > 1:
                    continue
                previous = spans[index - 1][1] if index > 0 else 0
                following = spans[index + 1][0] if index + 1 < len(spans) else len(clause)
                before, after = clause[max(previous, lo - 160) : lo], clause[hi:following]
                strict = _deadline_kind(before, after)
                if strict is not None:
                    if strict_guarded is None:
                        strict_guarded = _NOT_OWED.search(clause) is not None
                    if not strict_guarded:
                        hits.add(strict)
                        # a strict date still to come covers its kind here (two dates for one obligation)
                        day = mention.as_date()
                        if (
                            day is not None
                            and (start is None or day > start)
                            and (today is None or day >= today)
                        ):
                            covered.add(strict)
                    continue  # the strict path's (deadline_items); without its year, nobody's
                if nothing:
                    continue  # a page that says nothing needs doing
                if _PERIOD_END.search(clause[max(0, lo - 160) : lo]) or _RANGE_START.match(after):
                    continue  # what the payment is for; a window's first date
                # none without its year: such a date files nothing (2026-10-07 re-review)
                day = mention.as_date()
                if day is None or (start is not None and day <= start) or (today is not None and day < today):
                    continue  # no day, the letter's own date or one before it, or past when the letter was read
                if (
                    day in quoted
                    or day in series
                    or any(abs((day - other).days) <= DEADLINE_REACH for other in taken)
                ):
                    continue  # read by the reading, an instalment of its, or within 3 days of a to-do of its
                ended = bisect.bisect_right(greeting_ends, lo)
                cut = greeting_ends[ended - 1] if ended else 0
                following_greeting = bisect.bisect_left(greeting_starts, hi)
                stop = (
                    greeting_starts[following_greeting]
                    if following_greeting < len(greeting_starts)
                    else len(clause)
                )
                own_start = max(previous, lo - 160, cut)
                own = clause[own_start:lo]
                tail = after[: min(len(after), stop - hi, 120)]
                matched = _loose_family(own, tail)
                if matched is None:
                    continue
                family = matched.family
                if family.shape in _ASKING and not _OPENS.fullmatch(clause, cut, own_start + matched.start):
                    continue  # words before it in its sentence: perhaps a condition or a group no list names
                if family.shape == "label" and not _LABEL_ENDS.match(tail):
                    continue  # more words after a label's date: perhaps a window's first day
                region = regions.get((cut, stop))
                if region is None:
                    region = regions[(cut, stop)] = _Region(clause[cut:stop], sender)
                if region.guarded:
                    continue
                kind: _Kind | None
                if family.shape in ("label", "labelled"):
                    line_before = own[own.rfind("\n") + 1 :]
                    newline = tail.find("\n")
                    kind = _label_kind(matched.words, line_before + (tail if newline < 0 else tail[:newline]))
                else:
                    told = family.kind or _verb_kind(matched.words)
                    named = _nouns_kind(f"{own} {tail}")
                    if told is not None and named is not None and named != told:
                        continue  # "Senden Sie uns den Betrag": money sent — unclear what is asked
                    kind = told or named
                if kind is None:
                    continue  # unclear what is asked: no to-do
                if family.shape in ("sentence", "asker") and not _YOU_ACT.search(matched.words):
                    continue  # "… senden sie uns …": they, not the person
                if family.shape in ("sentence", "imperative") and not region.toward(kind):
                    continue
                if kind == "payment" and (by_label_only or (paying and _FULL_PRICE.search(clause))):
                    continue  # a debit's, a paid letter's or a payout's day; the full price of the reading's payment
                found = _Found(day, kind, clause, lo, hi, previous, False)
                if family.shape in ("label", "labelled"):
                    labels.append(found)
                else:
                    consider(found)
        # a label is the person's when the page asks her for its kind (in words, or a strict date) — never on a page of
        # a holiday, opening hours, an offer or event, a statement or a status letter
        if labels and not (closed or _NOT_A_DEMAND.search(flat) or _STATUS.search(flat)):
            asks = hits | _page_asks(clauses)
            for found in labels:
                if found.kind in asks:
                    consider(found)
    return [found for kind, found in earliest.items() if kind not in covered]


def _deadline_kind(before: str, after: str) -> Literal["payment", "declaration"] | None:
    """Whether the words around a date set it as the day the person must pay or send something by in strict words: a
    payment's label, a second-person or imperative verb, or "zu zahlen" / "einzureichen" / "fällig" after it. Looser
    words are :func:`_loose_family`'s (:func:`_looser_dates`), asked only when these say nothing, and guarded more."""
    if _PAY_LABEL.search(before) or _PAY_YOU.search(before):
        return "payment"
    by = re.search(_BY, before, re.IGNORECASE) is not None
    if (by and _PAY_AFTER.match(after)) or (_DUE_BEFORE.search(before) and _DUE_AFTER.match(after)):
        return "payment"
    sent = _SEND_YOU.search(before)
    if sent and (_SEND_WHOLE.search(sent.group()) or _SEND_PREFIX.match(after)):
        return "declaration"
    if by and _SEND_AFTER.match(after):
        return "declaration"
    return None


#: How far around a date its line is read for the words that set it (:func:`_quote_around`): beyond every strict
#: pattern's reach, so the line's quote is the one the whole line gives.
_QUOTE_WINDOW = 300


def _quote_around(clause: str, start: int, end: int, sets: Any = _sets_strictly) -> str:
    """The to-do's quote: the date's own line when its words there set it (``sets``: "Fällig am: 15.10.2026" in a box
    of the header — never the letterhead and the address above it), else its sentence when short, else the words
    around the date within the sentence. The line is read within :data:`_QUOTE_WINDOW` characters of the date, never
    whole (a line of many dates is read once per to-do, not once per date)."""
    line_start = clause.rfind("\n", max(0, start - _QUOTE_WINDOW), start) + 1
    line_end = clause.find("\n", end, end + _QUOTE_WINDOW)
    before = clause[max(line_start, start - _QUOTE_WINDOW) : start]
    after = clause[end : line_end if line_end >= 0 else min(len(clause), end + _QUOTE_WINDOW)]
    if sets(before, after):
        line_start = clause.rfind("\n", 0, start) + 1
        line_end = clause.find("\n", end)
        return _flat(clause[line_start : len(clause) if line_end < 0 else line_end])
    flat = _flat(clause)
    if len(flat) <= QUOTE_CAP:
        return flat
    low, high = max(0, start - 240), min(len(clause), end + 240)
    return _flat(clause[low:high].split(" ", 1)[-1].rsplit(" ", 1)[0])


def _reading_days(extraction: DocumentExtraction, start: date | None, today: date | None) -> list[date]:
    """The days the reading's own to-dos fall on (a relative one counted in a plain context from the reading's
    date, else the letter's)."""
    from ordnung.rules import compute_due  # the rules engine's entry point

    written = _iso(extraction.document_date) or start
    ctx = RuleContext(today=today or written or date.today(), document_date=written)
    days: list[date] = []
    for item in extraction.items:
        spec = item.date
        day: date | None = None
        if spec.type == "fixed":
            day = _iso(spec.date)
        elif spec.type == "relative":
            try:
                day = _iso(compute_due(spec, ctx).due_date)
            except (ValueError, KeyError, TypeError):  # a period the engine can't count: no day of its own
                day = None
        if day is not None:
            days.append(day)
    return days


#: How many later occurrences of a recurring to-do of the reading count as its own days (five years of months).
_OCCURRENCES = 61


def _series_days(extraction: DocumentExtraction) -> set[date]:
    """The later days a recurring to-do of the reading falls on (an installment plan, monthly advance payments:
    "Fällig am 15.12.2026" in its rows) — the very day only: a date a few days off one (a back payment due on the
    31st beside an advance due each 1st) is another obligation; never for a rule by working day."""
    from ordnung.recurrence import occurrence  # recurrence imports the store: no import at the module's top

    days: set[date] = set()
    for item in extraction.items:
        first = _iso(item.date.date) if item.date.type == "fixed" else None
        if first is not None and item.recurrence is not None and item.recurrence.working_day is None:
            days.update(occurrence(first, item.recurrence, n) for n in range(1, _OCCURRENCES))
    return days


def _undated_series(extraction: DocumentExtraction) -> set[int]:
    """The days of the month a recurring payment of the reading without a date falls on ("jeweils zum 15."): the
    letter's rows on that day are its occurrences once it lists two or more of them (:func:`deadline_items`)."""
    return {
        item.recurrence.day_of_month
        for item in extraction.items
        if item.kind == "payment"
        and item.date.type != "fixed"
        and item.recurrence is not None
        and item.recurrence.working_day is None
        and item.recurrence.day_of_month is not None
    }


#: How many dates the reading left out get a to-do of code's, the earliest kept (a letter of 40 send-by lines files 3).
DEADLINE_MAX = 3


def deadline_items(
    extraction: DocumentExtraction, pages: Sequence[PageInput], *, today: date | None = None
) -> list[ExtractedItem]:
    """The to-dos for fixed dates the letter's visible text sets for the person and the reading left out.

    Strict words (as before 2026-10-07, unchanged): a date with its year that a payment's label ("Zahlbar bis", "Fällig
    am:", "Due date:") or a second-person or imperative verb sets ("Bitte überweisen Sie … bis zum …", "… ist bis zum
    … zu zahlen", "ist am … fällig", "Bitte reichen Sie … bis zum … ein", "… bis spätestens … vorzulegen", "please pay
    / submit … by …": :func:`_deadline_kind`) — never in a sentence that names a remedy (the check of
    :func:`check_item` is for those), a condition, something past or already done, the sender's own act or a direct
    debit, an appointment, a discount or a preference, a validity, or an option the person may take (:data:`_NOT_OWED`,
    a request right after a question offering one: :data:`_OPTION_ASKED`); never a period's end (:data:`_PERIOD_END`);
    never the letter's own date or one before it, nor one already past on ``today`` (the day the letter arrived or is
    read: never an overdue to-do from code); and only when no dated to-do of the reading falls within
    :data:`DEADLINE_REACH` days of it, none quotes a sentence with that date (the reading read it), and it is no later
    occurrence of a recurring to-do of the reading (:func:`_series_days`, :func:`_undated_series`). A payment's label
    or "fällig" sets none on a letter that collects by direct debit, is paid or a credit note, or pays out
    (:func:`_not_owed_by_label`), nor does the full price beside a reading's payment dated by its discount
    (:data:`_FULL_PRICE`); and no payment comes back that a reading's warning doubts (:data:`_PAY_DOUBT`).

    Since 2026-10-07 (ADR 0015), beside them and guarded more (:func:`_looser_dates`): a date with its year in a
    looser wording that asks the person in its own words at its sentence's start, or in a label on a page that asks her
    for its kind — at most one of each kind, only for a kind neither the reading's dated to-dos nor a strict date of the
    letter still to come covers. A date without its year files nothing, as before.

    At most :data:`DEADLINE_MAX`, the strict ones first, the earliest. Each is ``low`` and "Please check"
    (:data:`~ordnung.ingest.verify.DEADLINE_LEFT_OUT`), worded as a cross-check of the letter, its quote the letter's
    own line or sentence, its date the one the letter writes (never moved: ``shift_rule="none"``). None for an almost
    blank reading (its own to-do sends the person to the letter: :func:`check_item`) or one that calls the letter a
    scam (a payment it rightly left out is never brought back)."""
    if _empty(extraction) or any(_SCAM.search(warning) for warning in extraction.warnings):
        return []
    start = letter_date(extraction, pages, today=today) or _iso(extraction.document_date)
    doubted = any(_PAY_DOUBT.search(warning) for warning in extraction.warnings)
    taken = _reading_days(extraction, start, today)
    # a date the letter gives a to-do of the reading too ("Zahlbar bis" in a box beside the text's date): set beside
    # that to-do already, the earlier kept (conflicts.find_rivals, settle) — no to-do of its own
    taken += [
        day
        for item in extraction.items
        for rival in find_rivals(item, extraction.items, pages)
        if rival.spec.type == "fixed" and (day := _iso(rival.spec.date)) is not None
    ]
    # a date in a sentence a to-do of the reading quotes: the reading read it (a date it misread there is the quote
    # check's to flag, verify.consistency_reasons) — no second to-do for that sentence
    quoted = {
        day
        for item in extraction.items
        for _start, _end, mention in date_spans(fold_punctuation(item.quote or ""))
        if (day := mention.as_date()) is not None
    }
    series = _series_days(extraction)
    # a letter that collects by direct debit, is paid already or a credit note, or pays out: a payment's label or
    # "fällig" sets no payment of the person's — a "Bitte zahlen Sie … bis" still does (the to-do is "Please check")
    by_label_only = _not_owed_by_label(pages)
    paying = any(item.kind == "payment" for item in extraction.items)
    found: dict[tuple[date, str], _Found] = {}
    for page in pages:
        clauses = _clauses(_visible(page))
        for at, (clause, _dated) in enumerate(clauses):
            if _REMEDY.search(clause) or _NOT_OWED.search(clause):
                continue
            asked = clauses[at - 1][0].strip() if at > 0 else ""
            if _OPTION_ASKED.search(asked) and not _W_QUESTION.match(asked):
                continue  # "Sie möchten Ihren Vertrag nicht verlängern? Dann senden Sie …": an option's request
            spans = date_spans(clause)
            readings = Counter((lo, hi) for lo, hi, _mention in spans)  # an ambiguous slash date reads twice
            for index, (lo, hi, mention) in enumerate(spans):
                day = mention.as_date()
                if day is None or mention.year is None or mention.ambiguous or readings[(lo, hi)] > 1:
                    continue
                if start is not None and day <= start:
                    continue  # the letter's own date, or one before it (a reminder's old due day)
                if (today is not None and day < today) or day in quoted:
                    continue  # past when the letter arrived or was read (never an overdue to-do from code), or read
                previous = spans[index - 1][1] if index > 0 else 0
                following = spans[index + 1][0] if index + 1 < len(spans) else len(clause)
                before = clause[max(previous, lo - 160) : lo]
                if _PERIOD_END.search(clause[max(0, lo - 160) : lo]):
                    continue  # "für den Zeitraum bis zum 31.12.2026": what the payment is for
                kind = _deadline_kind(before, clause[hi:following])
                if kind is None or any(abs((day - other).days) <= DEADLINE_REACH for other in taken):
                    continue
                payment = kind == "payment"
                if day in series or (payment and (doubted or (paying and _FULL_PRICE.search(clause)))):
                    continue  # an instalment of the reading's, a payment it doubts, the full price of its payment
                if payment and by_label_only and not _PAY_YOU.search(before):
                    continue  # the debit's day, a paid or credited box, a payout's day
                # the first sentence that sets it is its quote (its to-do is written only once kept)
                found.setdefault((day, kind), _Found(day, kind, clause, lo, hi, previous, True))
    # the rows of a recurring payment of the reading without a date ("jeweils zum 15.": "Fällig am 15.02.2027", …):
    # its occurrences once the letter lists two or more on its day — one alone may be the first date it left out
    for day_of_month in _undated_series(extraction):
        rows = [key for key in found if key[1] == "payment" and key[0].day == day_of_month]
        if len(rows) >= 2:
            for key in rows:
                del found[key]
    # two dates the letter gives one obligation (the text's and its payment box's): the earliest only — settle names
    # the other in its receipt, the earlier kept (conflicts.find_rivals); at most DEADLINE_MAX, the rivals found again
    # only when one is kept (never once per date)
    kept: list[ExtractedItem] = []
    rivaled: set[str | None] = set()
    for _key, candidate in sorted(found.items(), key=lambda pair: pair[0][0]):
        if candidate.day.isoformat() in rivaled:
            continue
        kept.append(_deadline_item(candidate))
        if len(kept) >= DEADLINE_MAX:
            break
        rivaled = {
            rival.spec.date
            for other in kept
            for rival in find_rivals(other, [*extraction.items, *kept], pages)
            if rival.spec.type == "fixed"
        }
    # a date in looser words (ADR 0015, 2026-10-07): after the strict ones, within the cap
    looser = _looser_dates(
        extraction,
        pages,
        start=start,
        today=today,
        taken=taken,
        series=series,
        paying=paying,
        by_label_only=by_label_only,
    )
    for candidate in sorted(looser, key=lambda found: found.day):
        if len(kept) >= DEADLINE_MAX:
            break
        kept.append(_deadline_item(candidate))
    return sorted(kept, key=lambda item: item.date.date or "")


#: The title of code's to-do for a date the reading left out (:func:`deadline_items`): a cross-check, not a demand.
DEADLINE_TITLE = "Check this date in the letter"


def _deadline_item(found: _Found) -> ExtractedItem:
    """Code's to-do for a date the reading left out (:func:`deadline_items`): a cross-check of the letter, never a
    demand (:data:`DEADLINE_TITLE`)."""
    from ordnung.rules.explain import fmt_date

    payment = found.kind == "payment"
    what = "a payment date" if payment else "a send-by date"
    clause, lo, hi = found.clause, found.lo, found.hi
    return ExtractedItem(
        kind="payment" if payment else "deadline",
        title=DEADLINE_TITLE,
        action=(
            f"The letter names {what} on {fmt_date(found.day)} that Claude's reading didn't list — check whether it "
            "applies to you before acting."
        ),
        date=DateSpec(
            type="fixed",
            date=found.day.isoformat(),
            nature=found.kind,
            shift_rule="none",
            text=_flat(clause[max(found.previous, lo - 60) : hi]),
        ),
        priority="normal",
        quote=_quote_around(clause, lo, hi, _sets_strictly if found.strict else _sets_loosely),
    )


#: How the letter's warning for such to-dos starts (:func:`deadline_warning`).
DEADLINE_WARNING_PREFIX = "Claude's reading of this letter left out"


def deadline_warning(count: int) -> str:
    """The letter's warning for the dates the reading left out (:func:`deadline_items`)."""
    them = "it" if count == 1 else "them"
    dates = "a date" if count == 1 else f"{count} dates"
    todos = "a to-do" if count == 1 else "to-dos"
    return (
        f"{DEADLINE_WARNING_PREFIX} {dates} the letter sets for you. Ordnung added {them} as {todos} from the letter's "
        f"own words — please check {them} against the letter."
    )


def deadline_slots(items: Sequence[ExtractedItem]) -> list[str]:
    """The slots of such to-dos, one per date and kind (``check:deadline#2026-10-23-declaration``): stable when
    a later reading files another set, so a to-do the person acted on never takes over another date."""
    return [f"{DEADLINE_SLOT}#{item.date.date}-{item.date.nature}" for item in items]


def is_check_slot(slot: str | None) -> bool:
    """A to-do code filed for an incomplete reading: the objection's or a placeholder (:data:`CHECK_SLOT`), or a
    date the reading left out (:data:`DEADLINE_SLOT`)."""
    return bool(slot) and (slot == CHECK_SLOT or str(slot).split("#")[0] == DEADLINE_SLOT)
