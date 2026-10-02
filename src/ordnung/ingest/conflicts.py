"""Two dates for one obligation: a letter that contradicts itself (SPEC § 8 stage 6, § 21).

A letter sometimes prints two different dates for the same thing: "binnen 14 Tagen nach dem
Rechnungsdatum" in the text and "Zahlbar bis" a week later in the payment box, or a tax notice
dated one day in its header and another in its first sentence ("Mit diesem Bescheid vom …"). The
reading takes one of them, and nothing in its own sentence tells that the letter says otherwise
elsewhere. This module checks, in code and on the letter's own text, every dated to-do for such a
second statement:

* :func:`find_rivals` (verify stage) looks in the page text for other deadline statements of the
  same nature as a to-do: for a payment, a date after "zahlbar bis", "fällig am", "bitte überweisen
  Sie … bis zum", "Zahlungsziel:" (or before "… fällig", "… zu zahlen"), and a period after the
  invoice's date or its arrival ("binnen 14 Tagen nach Rechnungsdatum"); for an objection, a date
  after "Widerspruch / Einspruch / Klage … bis"; for a notice (a cancellation that must arrive) or a
  declaration (a form, documents, a statement or a consent to send), a date after a deadline word —
  "bis (zum)", "spätestens", "by", "no later than", "is due on", never a bare "zum" or "am" (a notice
  "zum 31.12." names the end it takes effect) — or a deadline label ("Abgabefrist:", "Einsendeschluss:"),
  with the nature's words on its label or in its sentence ("Kündigung", "kündigen"; "Unterlagen",
  "Fragebogen", "Stellungnahme", "einreichen", "zurücksenden", "form", "submit") and, without a label,
  the act it is the last day for ("einreichen", "vorlegen", "bei uns eingehen", "vorliegen", "submit",
  "be received"; for a notice the cancellation named before the date in its own clause, or "bis …
  kündigen") — never how long something lasts ("gilt bis", "ist bis … gültig", "läuft bis", "verlängert
  sich bis", "weiter beliefert", "continues until") or a relative clause's date ("Unterlagen, die bis …
  eingehen, bearbeiten wir noch …") — and a period after this letter's date or its arrival ("binnen 14
  Tagen nach Zugang dieses Schreibens", never "nach Erhalt unseres Schreibens vom …"); and, for any
  period counted from the letter, a date the letter gives for itself ("mit diesem Bescheid vom …", "mit
  Bescheid vom … entscheiden wir", "this letter dated …", and the first "Datum:" / "Date:" label of its
  first page's header, :func:`_header_date` — on the label's line or right under it on the page, never
  a "Datum" in its body, a table's, an event's or another decision's, nor a date that reads two ways).
  Only statements that plausibly concern the *same* obligation count:
  never a recurring to-do, money coming in, or a to-do with no date; never a statement whose sentence
  is the to-do's own quote, whose date is another to-do's, which names a different amount (an
  instalment), a kind of payment the to-do's sentence does not (instalments, a prepayment, a fee, a
  direct debit, a series: "die neuen Abschläge … erstmals am", "die nächste Vorauszahlung"), or —
  for an objection — another remedy (a Klage's date is not a Beschwerde's), for a declaration
  something else to send (the documents' date is not the questionnaire's; a to-do naming none has no
  rival), for a notice another right to cancel (a *Sonderkündigungsrecht* is not the ordinary notice),
  which is written in the past ("war fällig am …", "wurde"), or which is an early-payment discount
  (*Skonto*: paying after the discount date is not late — the net date is the obligation, so a discount
  date is never a second due date) or, for a notice or a declaration, an optional earlier day
  ("möglichst bis", "wenn möglich", a bonus for answering early). The page's line breaks stay: a due
  word counts for a date only on the date's own
  label or in its sentence, never from another label ("Rechnungsdatum: …" above "Zahlbar bis: …"),
  and a remedy's sentence gives no payment period.
* :func:`settle` (compute stage) computes each such statement with the rules engine, as the to-do's
  own date is computed. A statement whose date is the to-do's, or a written date on or before the
  letter's own (the letter's date itself; a reminder repeats the original invoice's due date:
  history, not a second date — before the day it arrived, or today, when the letter's date was not
  read), is no conflict; nor is a reminder's period "after the invoice date" (it counts from the old
  invoice's date, not the reminder's), a date before the letter's own date as read, or a date the letter
  gives for itself more than :data:`_LETTER_DATE_REACH` days from the one read (it is another's: an old
  invoice's, an offence's). When the letter does give another date, the to-do keeps the **earlier** one (the safe
  side: acting by it is on time whichever applies), its receipt names both dates and says why the
  earlier one was kept (rule ``conflicting_dates``), its confidence is ``low`` and it is marked
  "Please check" (its evidence is not ``value_consistent``: :func:`~ordnung.ingest.plan.needs_check`).
  A date the letter gives for itself that is later than the one read leaves the to-do's date as it is
  (it is already the earlier) but is named all the same: the letter contradicts itself.
* :func:`settle_law` does the same for the deadlines the law adds to a high-stakes letter
  (:func:`~ordnung.ingest.plan.sync_rule_items`): counted from the letter's date or its arrival, each is
  counted from every date the letter gives for itself (:func:`law_rivals`) and keeps the earliest.

The check reads code-side only (no model call) and adds dates only where the letter writes them.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

from ordnung.ingest.normalize import fold_punctuation, normalise_with_map
from ordnung.ingest.text import PageText, Word
from ordnung.ingest.verify import (
    PageInput,
    date_spans,
    grade_reading,
    parse_amounts,
    parse_periods,
)
from ordnung.models import (
    PAYMENT_DEMAND_KINDS,
    ComputationReceipt,
    ComputationStep,
    DateSpec,
    ExtractedItem,
    Grounding,
    Page,
)
from ordnung.rules import RuleContext, catalog, compute_due
from ordnung.rules.deadlines import parse_date
from ordnung.rules.explain import fmt_date

#: The rule a receipt cites when the letter gives two dates for the to-do (and the reason its evidence
#: is not value-consistent).
CONFLICTING_DATES = "conflicting_dates"

#: How far (characters, in the letter's flattened text) a deadline word may stand from its date.
_CUE_REACH = 90
_AFTER_REACH = 60
#: Characters around a statement in which an amount belongs to it.
_AMOUNT_REACH = 80
#: How much of a statement a warning quotes.
_QUOTE_CHARS = 90
_COUNTS = {2: "two", 3: "three"}
#: How many days a date the letter gives for itself may stand from the one read and still be its own.
_LETTER_DATE_REACH = 14

_PAYMENT_CUE = re.compile(
    r"\b(?:zahlbar|fällig\w*|zahlungsziel|zahlungstermin|zahlungsfrist|zahlen\s+sie|überweisen\s+sie"
    r"|begleichen\s+sie|zu\s+(?:zahlen|überweisen|begleichen)|payable|please\s+pay|to\s+be\s+paid"
    r"|(?:payment|amount|total|balance)\s+(?:is\s+)?due|due\s+date|pay(?:ment)?\s+(?:by|before|until|within))\b",
    re.IGNORECASE,
)
#: A payment's words after its date: "bis zum 15.05.2026 zu zahlen", "ist am 15.11.2026 fällig".
_PAYMENT_CUE_AFTER = re.compile(
    r"^\W*(?:\S+\s+){0,6}?(?:fällig|zu\s+zahlen|zu\s+überweisen|zu\s+begleichen|zahlbar)\b", re.IGNORECASE
)
_OBJECTION_CUE = re.compile(r"\b(?:widerspruch|einspruch|klage|objection|appeal)\w*", re.IGNORECASE)
_WEEKDAY = (
    r"(?:(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday),?\s*)?"
)
#: The words just before a due date: "bis (zum)", "spätestens", "am", "by" … or a label's colon —
#: a weekday may stand between ("bis Freitag, 28.08.2026").
_DUE_PREPOSITION = re.compile(
    rf"(?:\b(?:bis|zum|spätestens|einschließlich|am|by|on|before|until)|:)\s*{_WEEKDAY}(?:den\s+)?$",
    re.IGNORECASE,
)
#: The words just before the last day of a notice or a declaration: "bis (zum)", "spätestens (am)",
#: "by", "no later than", "is due on" — never a bare "zum" or "am" ("kündigen zum 31.12.2026" names the
#: end the notice takes effect, not the day it must arrive by) — or the colon of a label that names a
#: deadline ("Abgabefrist:", "Einsendeschluss:", "Deadline:"), not one that names a date ("Stand:").
_DEADLINE_PREPOSITION = re.compile(
    r"(?:\b(?:bis|spätestens|by|before|until)(?:\s+(?:zum|am|spätestens|einschließlich|bis))*"
    rf"|\b(?:no|not)\s+later\s+than|\bdue(?:\s+(?:on|by))?)\s*{_WEEKDAY}(?:den\s+)?$",
    re.IGNORECASE,
)
_DEADLINE_LABEL = re.compile(
    rf"(?:frist|einsendeschluss|abgabe|rückgabe|rücksendung|deadline|\bbis\b|spätestens)[^:\n]*:\s*{_WEEKDAY}$",
    re.IGNORECASE,
)
#: A notice: a cancellation or termination the person must send ("Kündigung", "kündigen", "cancel") —
#: never an announcement ("Ankündigung", "wie angekündigt").
_NOTICE_CUE = re.compile(r"\b(?!an(?:ge)?kündig)\w*kündig\w*|\bcancel\w*|\bterminat\w*", re.IGNORECASE)
#: The notice's own verb right after its date: "bis zum 31.08.2026 (schriftlich) kündigen", "… gekündigt
#: werden" — never one in another clause (", wenn Sie kündigen").
_NOTICE_VERB_AFTER = re.compile(
    r"^\s*(?:\w+\s+){0,2}?(?:zu\s+)?(?:ge)?kündig(?:en|t)\b|^\s*(?:\w+\s+){0,2}?(?:to\s+)?(?:cancel|terminate)\b",
    re.IGNORECASE,
)
#: The person's act a notice's or a declaration's date is the last day for: sending, handing in or
#: returning it, or its arriving ("einreichen", "vorlegen", "zurücksenden", "bei uns eingehen", "uns
#: vorliegen", "zugehen", "übermitteln", "submit", "return", "be received", "reach us") — or cancelling,
#: or exercising a right to.
_SENT = re.compile(
    r"\b(?:ein|nach)(?:zu|ge)?reich(?:en|t)\b|\breichen\s+sie\b|\bvor(?:zu|ge)?leg(?:en|t)\b|\blegen\s+sie\b"
    r"|\b(?:zurück|ein|zu)?(?:zu|ge)?(?:send|sand|schick)(?:en|et|t|e)?\b|\b(?:zurück|ab)(?:zu|ge)?geb(?:en|t)\b"
    r"|\bgeben\s+sie\b|\bübers(?:end|and)(?:en|t)?\b|\bübermitt(?:eln|elt|le)\b|\bein(?:zu|ge)?g(?:eh(?:en|t)|angen)\b"
    r"|\bvor(?:zu)?lieg(?:en|t)\b|\bzu(?:zu|ge)?g(?:eh(?:en|t)|angen)\b|\beintreff(?:en)?\b"
    r"|\bmit(?:zu|ge)?teil(?:en|t)\b|\bteilen\s+sie\b|\berteil(?:en|t)\b|\bhoch(?:zu|ge)?lad(?:en)?\b"
    r"|\b(?!an(?:ge)?kündig)\w*kündig(?:en|t|e)\b|\bausüb(?:en|t)\b|\bauszuüben\b|\bgeltend\b"
    r"|\bsubmi\w*|\breturn\w*|\bsend(?:s|ing)?\b|\bupload\w*|\breceived?\b|\breach(?:es)?\s+us\b|\barriv\w*"
    r"|\bcancel\b|\bterminate\b|\bexercis\w*",
    re.IGNORECASE,
)
#: Words of a validity, a term or a continuation: a date with one is how long something lasts ("gilt bis",
#: "ist bis … gültig", "läuft bis", "besteht bis", "verlängert sich bis", "weiter beliefert", "valid until",
#: "runs until", "continues until"), never the last day to send something.
_LASTS = re.compile(
    r"\b(?:gilt|gelten|gültig\w*|läuft|laufen|\w*laufzeit\w*|besteht|bestehen|verlänger\w*|garantier\w*"
    r"|weiter|fortgesetzt|fortbesteh\w*|befristet\w*|bleibt|bleiben|valid\w*|runs?|continues?|continued"
    r"|remains?|guarantee\w*|extend\w*|lasts?|in\s+force|in\s+kraft)\b",
    re.IGNORECASE,
)
#: A relative clause's start: "Unterlagen, die bis zum 15.09.2026 eingehen, bearbeiten wir noch …" names
#: which ones are handled first, not a deadline. The pronoun stands before a small word or a person ("die
#: bis", "die Sie"); an article stands before its noun (", die Unterlagen bis zum … einzureichen").
_RELATIVE_CLAUSE = re.compile(
    r"^\s*(?:(?:die|der|das|welche[rs]?)\s+(?:[a-zäöüß]\w*|Sie|Ihnen|Ihr|wir|uns)\b"
    r"|which\b|that\s+(?:is|are|arrive\w*|reach\w*|we|you)\b)"
)
#: A declaration: a form, documents or a statement to send, or the verbs that ask for one ("einreichen",
#: "zurücksenden", "submit", "return").
_DECLARATION_CUE = re.compile(
    r"\w*erklärung\w*|\w*fragebog\w*|\w*formular\w*|\bvordruck\w*|\bunterlagen\b|\w*nachweis\w*|\bbelege?\b"
    r"|\w*bescheinigung\w*|\bstellungnahme\w*|\w*anhörung\w*|\bäußer(?:n|ung\w*)\b|\bzustimmung\w*"
    r"|\beinwilligung\w*|\breichen\s+sie\b|\blegen\s+sie\b|\b(?:ein|nach)(?:zu|ge)?reich\w*"
    r"|\b(?:zurück|ein|zu)(?:zu|ge)?(?:send|sand|schick)\w*|\bzurück(?:zu|ge)?geb\w*|\bvor(?:zu|ge)?leg\w*"
    r"|\bübers(?:end|and)\w*"
    r"|\bdeclaration\w*|\bforms?\b|\bquestionnaire\w*|\bdocument(?:s|ation)?\b|\bsubmi\w*|\breturn(?:ed)?\b"
    r"|\bupload\w*|\bconsent\w*",
    re.IGNORECASE,
)
#: Words that make a notice's or a declaration's date optional — an earlier day that brings a benefit or
#: is only asked for if possible ("möglichst bis", "wenn Sie … bereits bis … einreichen, erhalten Sie"):
#: missing it is not late (as with *Skonto* for a payment), so it is never a second date.
_OPTIONAL = re.compile(
    r"\b(?:möglichst|nach\s+möglichkeit|wenn\s+möglich|gerne?|vorzugsweise|idealerweise|bereits|vorab"
    r"|frühzeitig|schon\s+jetzt|empfehl\w*|empfohl\w*|bonus|prämie\w*|vorteil\w*|rabatt|if\s+possible|ideally"
    r"|preferably|in\s+advance|early|earlier|already|recommend\w*|priority|vorrangig\w*|bevorzugt\w*)\b",
    re.IGNORECASE,
)
#: An early-payment discount: its date is not the due date ("ohne Abzug" is the net amount, which is).
_DISCOUNT = re.compile(r"skonto|discount|rabatt|nachlass|abzüglich|(?<!ohne )\babzug\b", re.IGNORECASE)
#: A statement about the past ("war fällig am …", "wurde … gesetzt"): history, not a date to meet.
_PAST = re.compile(r"\b(?:war|waren|wurde|wurden|hatte|hatten|was|were|had)\b", re.IGNORECASE)
_NUMBER = (
    r"\d{1,3}|eine[mnrs]?|ein|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|vierzehn|zwanzig"
    r"|dreißig|dreissig|one|two|three|four|five|six|seven|eight|nine|ten|fourteen|twenty|thirty"
)
_PERIOD_UNIT = (
    r"(?:kalender|bank)?(?:tag|tage|tagen|tages)|woche|wochen|monat|monate|monaten|monats"
    r"|(?:calendar\s+)?days?|weeks?|months?"
)
#: A payment period counted from the invoice's date or from its arrival, as the letter writes it.
_RELATIVE_PAYMENT = re.compile(
    rf"(?:\b(?:binnen|innerhalb(?:\s+von)?|within)\s+)?\b(?P<period>(?:{_NUMBER})\s+(?:{_PERIOD_UNIT}))\s+"
    r"(?:nach|ab|after|from|of)\s+(?:dem\s+|der\s+|the\s+)?"
    r"(?P<anchor>rechnungsdatum|rechnungsstellung|datum\s+(?:dieser|der)\s+rechnung"
    r"|rechnungseingang|rechnungserhalt|erhalt|zugang|date\s+of\s+(?:this|the)\s+(?:letter|invoice)"
    r"|invoice\s+date|receipt)\b",
    re.IGNORECASE,
)
_ARRIVAL_ANCHORS = ("rechnungseingang", "rechnungserhalt", "erhalt", "zugang", "receipt")
#: A notice's or a declaration's period counted from this letter's date or its arrival ("binnen 14 Tagen
#: nach Zugang dieses Schreibens", "within 10 business days of the date of this letter") — never from
#: another letter's ("nach Erhalt unseres Schreibens vom …").
_RELATIVE_LETTER = re.compile(
    rf"(?:\b(?:binnen|innerhalb(?:\s+von)?|within)\s+)?\b(?P<period>(?:{_NUMBER})\s+"
    rf"(?:(?:business|working)\s+days?|\w*werktag\w*|\w*arbeitstag\w*|{_PERIOD_UNIT}))(?:\s*\([^)]*\))?\s+"
    r"(?:nach|ab|after|from|of)\s+(?:dem\s+|the\s+)?"
    r"(?P<anchor>(?:zugang|erhalt|receipt)(?:\s+(?:of\s+)?(?:dieses|this)\s+(?:schreibens|briefes|letter))?"
    r"|datum\s+(?:dieses|des)\s+(?:schreibens|briefes)|briefdatum|date\s+of\s+(?:this|the)\s+letter)\b"
    r"(?!\s+(?:unsere[sr]?|ihre[sr]?|des|der|of|our|your|the)\b)",
    re.IGNORECASE,
)
_LETTER_ARRIVAL = ("zugang", "erhalt", "receipt")
#: The letter naming its own date: "(mit) diesem Bescheid vom …", "this letter dated …".
_SELF_DATE = re.compile(
    r"(?:\b(?:diese[mnrs]?|vorliegende[mnrs]?)\s+\w*(?:bescheid|schreiben|brief|mahnung|erinnerung"
    r"|aufforderung|mitteilung|festsetzung)|\bthis\s+(?:letter|notice|decision|assessment))\s+"
    r"(?:vom|dated|of)\s*$",
    re.IGNORECASE,
)
#: "mit Bescheid vom 16.03.2026 entscheiden wir …": the letter's own decision, in the present tense.
_OWN_DECISION_BEFORE = re.compile(r"\bmit\s+(?:dem\s+)?(?:bescheid|schreiben)\s+vom\s*$", re.IGNORECASE)
_OWN_DECISION_AFTER = re.compile(
    r"^\s*(?:entscheiden|setzen|lehnen|bewilligen|gewähren|fordern|erheben|stellen|teilen|ändern|heben"
    r"|erstatten|erlassen|bestätigen)\s+wir\b",
    re.IGNORECASE,
)
#: Where a sentence ends: a full stop, "!", "?" or ";" before a capital letter or an opening quote.
_SENTENCE_END = re.compile(r"[.!?;]\s+(?=[A-ZÄÖÜ\"(])")
#: A label's colon ("Rechnungsdatum: …", "Total due: …"), not a time's ("10:00").
_LABEL_COLON = re.compile(r":(?=\s|$)")
#: Where a label's words start on a line ("… fällig. Hinweis:", "02.03.2026 · Zahlbar bis:").
_FIELD_BREAK = re.compile(r"[.!?;,]\s|[·|(]|\s[-–]\s")
#: Words that mark another obligation than a one-off payment: an instalment, an advance payment, a
#: fee, a direct debit, a series ("erstmals am …", "jeweils", "monatlich", "die nächste …"). A statement
#: with one the to-do's own sentence lacks dates something else (a utility's new instalments, a tax
#: prepayment, a first premium collected from the account).
_OTHER_OBLIGATION: dict[str, re.Pattern[str]] = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in {
        "instalment": r"\babschl[aä]g\w*|\braten?\b|\w*ratenzahlung\w*|\bteil(?:zahlung|betr[aä]g)\w*"
        r"|\binstal+ments?\b|\b(?:folge|erst)(?:beitr[aä]g|rate)\w*",
        "advance": r"\bvorauszahlung\w*|\bprepayments?\b|\badvance\s+payments?\b",
        "fee": r"\w*gebühr\w*|\bfees?\b",
        "debit": r"\babgebucht\b|\babbuch\w*|\w*lastschrift\w*|\beingezogen\b|\beinzug\w*|\bdirect\s+debit\w*"
        r"|\bdebited\b",
        "series": r"\berstmal\w*|\bjeweils\b|\b(?:zu)?künftig\w*|\bnächste\w*|\bnext\b|\bthereafter\b"
        r"|\bsubsequent\w*|\beach\s+month\b|\bevery\s+month\b",
        "period": r"\w*monatlich\w*|\w*jährlich\w*|\bmonthly\b|\bquarterly\b|\bannual(?:ly)?\b|\byearly\b",
    }.items()
}
#: The remedy an objection statement names: a date for a Widerspruch is not one for a Klage.
_REMEDIES: dict[str, re.Pattern[str]] = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in {
        "widerspruch": r"widerspr\w*",
        "einspruch": r"einspr\w*",
        "klage": r"\bklage\w*|\bklagen\b",
        "beschwerde": r"beschwerde\w*",
        "objection": r"\bobjection\w*|\bobject\b",
        "appeal": r"\bappeal\w*",
    }.items()
}
#: What a declaration asks for: a date for the documents is not one for a form or a statement.
_DECLARED: dict[str, re.Pattern[str]] = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in {
        "documents": r"\bunterlagen\b|\bdokument\w*|\bbelege?\b|\w*nachweis\w*|\w*bescheinigung\w*|\w*auszüg\w*"
        r"|\w*abrechnungen\b|\bdocument(?:s|ation)?\b|\bproofs?\b|\bevidence\b|\bcertificates?\b|\breceipts\b",
        "form": r"\w*formular\w*|\bvordruck\w*|\w*fragebog\w*|\w*bogen\b|\bforms?\b|\bquestionnaire\w*",
        "declaration": r"\w*erklärung\w*|\bdeclarations?\b",
        "statement": r"\bstellungnahme\w*|\w*anhörung\w*|\bäußer(?:n|ung\w*)\b|\bstatement\b|\bcomments?\b",
        "consent": r"\bzustimm\w*|\bzustimmung\w*|\beinwillig\w*|\bconsent\w*",
    }.items()
}
#: Which notice: a date for a special right to cancel is not one for the ordinary notice.
_NOTICE_KINDS: dict[str, re.Pattern[str]] = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in {
        "special": r"\w*sonderkündig\w*|\baußerordentlich\w*|\bfristlos\w*|\bspecial\b|\bextraordinar\w*",
        "ordinary": r"\bordentlich\w*|\bordinary\b",
    }.items()
}
#: The label of the letter's own date in its header: "Datum: 02.03.2026", "Date: 5 May 2026" — on its own,
#: never a compound ("Rechnungsdatum", "Due date", "Date of birth") nor another decision's ("Datum des
#: Bescheids" in a Widerspruchsbescheid is the decision it rules on).
_HEADER_LABEL = r"(?P<label>datum|date)"
#: The label with its date on the same line, after a colon or a column's gap ("Datum   22.09.2026").
_HEADER_SAME_LINE = re.compile(
    rf"(?:^|[·|]\s*|\s{{2,}}|\t){_HEADER_LABEL}(?:\s*:\s*|\s{{2,}}|\t){_WEEKDAY}$", re.IGNORECASE
)
#: The label ending its line, its date ending the next ("… 44135 Musterstadt   Datum" over "27.04.2026").
_HEADER_LINE_END = re.compile(rf"(?:^|[·|]\s*|\s{{2,}}|\t){_HEADER_LABEL}\s*:?\s*$", re.IGNORECASE)
#: Words before a date that make it another one than the letter's ("Ihr Schreiben vom …").
_ANOTHER_DATE = re.compile(r"\b(?:vom|seit|bis|ab|am|zum|from|of|dated|since|until)\s*$", re.IGNORECASE)
#: A table's row: cells split by "|", a tab, or more than one column gap.
_TABLE_ROW = re.compile(r"[|\t]|\S\s{2,}\S.*\S\s{2,}\S")
#: A line naming an event, whose date is the event's: an offence, an appointment, a time of day.
_EVENT = re.compile(
    r"\b(?:uhrzeit|tatzeit|tatort|tattag|termin\w*|appointment|time)\b|\b\d{1,2}:\d{2}\b", re.IGNORECASE
)
#: How far (a share of the page's height) a column's value may stand under its label.
_UNDER_REACH = 0.05
#: An appointment's block around a "Datum:" line: its heading above ("Ihr Termin:"), its time below ("Uhrzeit: …").
_BLOCK_ABOVE = re.compile(r"\b(?:termin\w*|appointment|einladung|vorsprache)\b[^:]*:\s*$", re.IGNORECASE)
_BLOCK_BELOW = re.compile(r"^\s*(?:uhrzeit|time|beginn)\b", re.IGNORECASE)
#: Where a letter's body starts.
_SALUTATION = re.compile(r"(?:sehr\s+geehrte|guten\s+tag|hallo\b|liebe[rs]?\b|dear\b|hello\b)", re.IGNORECASE)

Nature = Literal["payment", "objection", "notice", "declaration"]
_NEW_NATURES = ("notice", "declaration")


@dataclass(frozen=True)
class Rival:
    """Another statement in the letter that dates a to-do's obligation: ``spec`` is what it says (a
    date, or a period and what it counts from), ``statement`` the letter's words, ``grounding`` how
    the page it stands on was read (a text layer: ``verified``; an AI transcript: ``model_read``).
    ``letter_date``: the statement is a date the letter gives for *itself*; ``spec`` is then the
    to-do's own, to be counted from that date instead of the letter's date as read. ``quote``: the page's
    own words to show as evidence, when ``statement`` joins words from two lines (default: it)."""

    spec: DateSpec
    statement: str
    grounding: Grounding = "verified"
    letter_date: date | None = None
    quote: str = ""
    #: The letter's own remedy notice set beside a reading's objection date (``gaps.notice_rival``), counted
    #: from the date the letter's first page names: computed without the letter's kind (no letter rule), and
    #: never left out as a reminder's or as before the reading's date.
    notice: bool = False
    #: That notice counts from formal service or arrival (a confirmed arrival is its start).
    served: bool = False

    @property
    def evidence(self) -> str:
        """The page's words this statement stands on."""
        return self.quote or self.statement


@dataclass(frozen=True)
class _Statement:
    """``window``: the text around the statement in which an amount belongs to it; ``context``: the words
    that stand with its date (not past a label or another date), in which a word marking another
    obligation or a remedy counts."""

    spec: DateSpec
    phrase: str
    window: str
    grounding: Grounding
    letter_date: date | None = None
    context: str = ""
    quote: str = ""


# --------------------------------------------------------------------------------------------------
# Finding the letter's statements (verify stage)
# --------------------------------------------------------------------------------------------------


def _page_text(page: PageInput) -> tuple[str, Grounding]:
    if isinstance(page, PageText):
        return page.text, "verified" if page.source == "text" else "model_read"
    if isinstance(page, Page):
        return page.text, "verified" if page.text_source == "text" else "model_read"
    return page[1], "verified" if page[3] == "text" else "model_read"


def _clauses(text: str) -> list[tuple[str, list[tuple[int, int, date]]]]:
    """The letter's text folded into sentences, each with its dated mentions (dates without a year are
    left out: they can't be compared). The line breaks stay (a label's line is its own:
    :func:`_label_before`); a full stop inside a date ("30. Juni") never ends a sentence."""
    lines = (re.sub(r"\s+", " ", line).strip() for line in fold_punctuation(text).splitlines())
    flat = "\n".join(line for line in lines if line)
    spans = [(start, end, found) for start, end, m in date_spans(flat) if (found := m.as_date()) is not None]
    inside = [(start, end) for start, end, _ in spans]
    cuts = [0]
    for match in _SENTENCE_END.finditer(flat):
        if not any(start <= match.start() < end for start, end in inside):
            cuts.append(match.start() + 1)
    cuts.append(len(flat))
    clauses = []
    for lo, hi in itertools.pairwise(cuts):
        clause = flat[lo:hi]
        local = [(s - lo, e - lo, d) for s, e, d in spans if lo <= s and e <= hi]
        clauses.append((clause, local))
    return clauses


def sentences(text: str) -> list[str]:
    """The letter's text folded into sentences (:func:`_clauses`, without their dates): whitespace runs
    collapsed, its line breaks kept, a full stop inside a date never ending one."""
    return [clause for clause, _ in _clauses(text)]


def _label_before(before: str) -> str:
    """The words before a date that are its own. On a label's line ("Zahlbar bis: 16.03.2026") the line
    itself, from the label before it on that line if any ("Fälligkeit: sofort, Datum: 02.03.2026" gives
    "sofort, Datum:"); otherwise the words back to the last label of an earlier line, never into it
    ("Gesamtbetrag fällig: 120,00 EUR" above "Datum: 02.03.2026": that "fällig" is the total's)."""
    line = before.rfind("\n") + 1
    colons = [m.start() for m in _LABEL_COLON.finditer(before)]
    own = [c for c in colons if c >= line]
    if own:
        return before[own[-2] + 1 :] if len(own) > 1 else before[line:]
    earlier = [c for c in colons if c < line]
    return before[earlier[-1] + 1 :] if earlier else before


def _label_after(after: str) -> str:
    """The words after a date that are its own: up to the next label, never into its words ("… 16.03.2026
    zu zahlen", but not the "Zahlbar bis:" after "Rechnungsdatum: 02.03.2026", on the next line or the
    same one)."""
    colon = _LABEL_COLON.search(after)
    if colon is None:
        return after
    line = after.rfind("\n", 0, colon.start())
    if line >= 0:
        return after[:line]
    breaks = list(_FIELD_BREAK.finditer(after, 0, colon.start()))
    return after[: breaks[-1].start()] if breaks else ""


def _new_nature(text: str) -> Nature | None:
    """A notice's or a declaration's words in ``text`` — neither when it names both, or a payment's or an
    objection's (whose statements are read as theirs)."""
    if _PAYMENT_CUE.search(text) or _OBJECTION_CUE.search(text) or re.search(r"zahlung|überweis", text, re.I):
        return None
    notice, declaration = bool(_NOTICE_CUE.search(text)), bool(_DECLARATION_CUE.search(text))
    if notice == declaration:
        return None
    return "notice" if notice else "declaration"


def _deadline(clause: str, start: int, end: int, before: str, after: str) -> tuple[Nature, str] | None:
    """The notice or the declaration a date is the last day of ("Kündigung … bis spätestens 30.09.2026",
    "Bitte reichen Sie die Unterlagen bis zum 15.03.2026 ein", "Abgabefrist: 31.07.2026", "must be received
    by"), with the words that say so: a deadline word just before it (never a bare "zum"/"am", nor a label
    that names no deadline), the nature's words on its label or in its sentence, and — unless a label names
    the deadline — the person's act it is the last day for (:data:`_SENT`: sending, handing in, its
    arriving; cancelling). For a notice the cancellation is named before the date in its own clause, or by
    the verb right after it ("bis zum 31.08.2026 kündigen"): "Der Schutz besteht bis …, wenn Sie kündigen"
    is no deadline. Never a date of how long something lasts in its own clause ("gilt bis", "ist bis …
    gültig", "läuft bis", "verlängert sich bis", "weiter beliefert", "continues until": :data:`_LASTS`),
    a relative clause's ("Unterlagen, die bis … eingehen, bearbeiten wir noch …"), one written in the past,
    or an optional one ("möglichst bis", "wenn Sie … bereits bis …, erhalten Sie")."""
    label = _DEADLINE_LABEL.search(before)
    strict = _DEADLINE_PREPOSITION.search(before) or label
    if strict is None:
        return None
    nature = _new_nature(before + after)
    if nature is None:
        return None
    clauses = re.split(r"[,;]", before)
    own_before = clauses[-1]  # the date's own clause: before it …
    own_after = re.split(r"[,;.!?]", after)[0]  # … and after it
    if _LASTS.search(f"{own_before} {own_after}"):
        return None
    if len(clauses) > 1 and _RELATIVE_CLAUSE.match(own_before):
        return None  # "Unterlagen, die bis … eingehen, …" (at a sentence's start "Die" is an article)
    if label is None and not _SENT.search(f"{before} {own_after}"):
        return None
    cue = _NOTICE_CUE if nature == "notice" else _DECLARATION_CUE
    if nature == "notice" and not cue.search(own_before) and not _NOTICE_VERB_AFTER.match(after):
        return None
    found = list(cue.finditer(before))
    head = min(found[-1].start(), strict.start()) if found else strict.start()
    tail = cue.search(after)
    said = before[head:] + clause[start:end] + (after[: tail.end()] if tail and not found else "")
    words = before + after
    if _PAST.search(said + after[:30]) or _OPTIONAL.search(words) or _DISCOUNT.search(words):
        return None
    return nature, said.strip()


def _explicit(clause: str, dates: list[tuple[int, int, date]], grounding: Grounding) -> list[_Statement]:
    """Dates the clause sets for a payment, an objection, a notice or a declaration ("Zahlbar bis:
    16.02.2026", "Widerspruch … bis zum 12.05.2026", :func:`_deadline`): a due word on the date's own label
    or in its sentence — never one of another label or beyond another date."""
    found = []
    for index, (start, end, day) in enumerate(dates):
        lo = dates[index - 1][1] if index > 0 else 0
        hi = dates[index + 1][0] if index + 1 < len(dates) else len(clause)
        before = _label_before(clause[max(lo, start - _CUE_REACH) : start])
        after = _label_after(clause[end : min(hi, end + _AFTER_REACH)])
        nature: Nature | None = None
        cue = None
        phrase = ""
        if _DUE_PREPOSITION.search(before):
            payment = list(_PAYMENT_CUE.finditer(before))
            objection = list(_OBJECTION_CUE.finditer(before))
            if payment:
                nature, cue = "payment", payment[-1].start()
            elif _PAYMENT_CUE_AFTER.search(after):
                nature, cue = "payment", len(before)
            elif objection:
                nature, cue = "objection", objection[-1].start()
        if nature is not None and cue is not None:
            said = (before[cue:] if cue < len(before) else before[-40:]) + clause[start:end] + after[:30]
            if _PAST.search(said) or _DISCOUNT.search(before + after):
                continue
            phrase = (before[cue:] + clause[start:end]).strip()
        elif (deadline := _deadline(clause, start, end, before, after)) is not None:
            nature, phrase = deadline
        else:
            continue
        spec = DateSpec(type="fixed", date=day.isoformat(), nature=nature, shift_rule="auto", text=phrase)
        window = clause[max(0, start - _AMOUNT_REACH) : end + _AMOUNT_REACH]
        found.append(_Statement(spec, phrase, window, grounding, context=before + clause[start:end] + after))
    return found


def _relative(clause: str, grounding: Grounding) -> list[_Statement]:
    """Payment periods the clause counts from the invoice's date or its arrival ("binnen 14 Tagen nach
    dem Rechnungsdatum", "Zahlungsziel: 7 Tage nach Rechnungsdatum")."""
    if not _PAYMENT_CUE.search(clause) and not re.search(r"zahlung|überweis", clause, re.IGNORECASE):
        return []
    if _PAST.search(clause) or _DISCOUNT.search(clause):
        return []
    if _OBJECTION_CUE.search(clause):
        return []  # a remedy's period ("Widerspruch … nach Zugang; die Zahlungspflicht bleibt"), not a payment's
    found = []
    for match in _RELATIVE_PAYMENT.finditer(clause):
        periods = parse_periods(match.group("period"))
        if len(periods) != 1:
            continue
        amount, unit = periods[0]
        anchor = match.group("anchor").casefold()
        spec = DateSpec(
            type="relative",
            anchor="receipt" if anchor in _ARRIVAL_ANCHORS else "document_date",
            amount=amount,
            unit=unit,
            nature="payment",
            shift_rule="auto",
            text=match.group().strip(),
        )
        window = clause[max(0, match.start() - _AMOUNT_REACH) : match.end() + _AMOUNT_REACH]
        context = (
            _label_before(clause[max(0, match.start() - _CUE_REACH) : match.start()])
            + match.group()
            + _label_after(clause[match.end() : match.end() + _AFTER_REACH])
        )
        found.append(_Statement(spec, match.group().strip(), window, grounding, context=context))
    return found


def _relative_deadline(clause: str, grounding: Grounding) -> list[_Statement]:
    """Notice and declaration periods the clause counts from this letter's date or its arrival ("Bitte
    reichen Sie die Unterlagen binnen 14 Tagen nach Zugang dieses Schreibens ein") — with the person's act
    they are the last days for, never how long something lasts ("gilt drei Monate nach Zugang")."""
    nature = _new_nature(clause)
    if nature is None or _PAST.search(clause) or _OPTIONAL.search(clause) or _DISCOUNT.search(clause):
        return []
    if _LASTS.search(clause) or not _SENT.search(clause):
        return []
    found = []
    for match in _RELATIVE_LETTER.finditer(clause):
        periods = parse_periods(match.group("period"))
        if len(periods) != 1:
            continue
        amount, unit = periods[0]
        anchor = match.group("anchor").casefold().split()[0]
        spec = DateSpec(
            type="relative",
            anchor="receipt" if anchor in _LETTER_ARRIVAL else "document_date",
            amount=amount,
            unit=unit,
            nature=nature,
            shift_rule="auto",
            text=match.group().strip(),
        )
        window = clause[max(0, match.start() - _AMOUNT_REACH) : match.end() + _AMOUNT_REACH]
        found.append(_Statement(spec, match.group().strip(), window, grounding, context=clause))
    return found


def _letter_dates(clause: str, dates: list[tuple[int, int, date]], grounding: Grounding) -> list[_Statement]:
    """Dates the letter gives for itself ("Mit diesem Bescheid vom 06.04.2027 setzen wir …")."""
    found = []
    for start, end, day in dates:
        before = clause[max(0, start - _CUE_REACH) : start]
        cue = _SELF_DATE.search(before)
        if cue is None and _OWN_DECISION_AFTER.match(clause[end:]):
            cue = _OWN_DECISION_BEFORE.search(before)
        if cue is None:
            continue
        phrase = (before[cue.start() :] + clause[start:end]).strip()
        found.append(
            _Statement(DateSpec(type="none", text=phrase), phrase, clause, grounding, letter_date=day)
        )
    return found


def _one_date(line: str, start: int, end: int) -> date | None:
    """The date written at ``line[start:end]`` — ``None`` when its day and month could be read either way
    (03/05/2026)."""
    days = {found for s, e, m in date_spans(line) if (s, e) == (start, end) and (found := m.as_date())}
    return days.pop() if len(days) == 1 else None


def _header(lines: list[str]) -> list[str]:
    """The lines of a letter's header: those before its salutation ("Sehr geehrte …", "Dear …") — without
    one, those before its first sentence or its first table (a row of cells: an invoice's number and date)."""
    for index, line in enumerate(lines):
        if _SALUTATION.match(line.strip()):
            return lines[:index]
    for index, line in enumerate(lines):
        if (
            _SENTENCE_END.search(line)
            or (line.rstrip().endswith(".") and len(line.split()) >= 4)
            or _TABLE_ROW.search(line)
        ):
            return lines[:index]
    return lines


def header(lines: list[str]) -> list[str]:
    """The lines of a letter's header (:func:`_header`): those before its salutation, else before its first
    sentence or table."""
    return _header(lines)


Box = tuple[str, float, float, float, float]


def _page_words(page: PageInput) -> list[Box]:
    """The page's words with their boxes (``text, x0, y0, x1, y1``; none for a transcript)."""
    words: Sequence[Any] = page.words if isinstance(page, PageText | Page) else page[2]
    boxes: list[Box] = []
    for word in words:
        if isinstance(word, Word):
            boxes.append((word.text, word.x0, word.y0, word.x1, word.y1))
        elif len(word) >= 5:
            boxes.append((str(word[0]), float(word[1]), float(word[2]), float(word[3]), float(word[4])))
    return boxes


def _under(words: list[Box], value: str) -> bool:
    """Whether the date ``value`` stands on the page right under a "Datum" / "Date" label — a column's
    value, not another column's."""
    labels = [box for box in words if fold_punctuation(box[0]).strip(":").casefold() in ("datum", "date")]
    token = value.split()[0].strip(".,;")
    values = [box for box in words if fold_punctuation(box[0]).strip(".,;") == token]
    return any(
        label[2] < found[2] < label[4] + _UNDER_REACH and min(label[3], found[3]) > max(label[1], found[1])
        for label in labels
        for found in values
    )


def _header_date(text: str, words: list[Box], grounding: Grounding) -> list[_Statement]:
    """The date the letter's header gives for it: the first "Datum:" / "Date:" label of its first page's
    header (:func:`_header`), with its date after it on the same line ("Datum: 02.03.2026", "Datum
    22.09.2026") or under it on the next (a column's label above its value: on the page, right under the
    label; without word boxes, the label and the date each alone on their line) — the only date on that
    line, ending it, and one that reads one way. Never a table's row or a line naming an event ("Tatort",
    "Uhrzeit", "Termin"), nor a date after "vom" ("Ihr Schreiben vom …"): an old invoice's, an offence's or
    an appointment's date is not the letter's."""
    lines = _header(fold_punctuation(text).splitlines())
    for index, line in enumerate(lines):
        for start, end, _ in date_spans(line):
            label = _HEADER_SAME_LINE.search(line[:start])
            if label is None:
                continue
            day = _one_date(line, start, end)
            above = lines[index - 1] if index else ""
            below = lines[index + 1] if index + 1 < len(lines) else ""
            if (
                day is None
                or "|" in line
                or _EVENT.search(line)
                or _BLOCK_ABOVE.search(above)
                or _BLOCK_BELOW.search(below)
            ):
                return []  # an appointment's block ("Ihr Termin:" / "Datum: …" / "Uhrzeit: …")
            phrase = re.sub(r"\s+", " ", line[label.start("label") : end]).strip()
            return [_Statement(DateSpec(type="none", text=phrase), phrase, line, grounding, letter_date=day)]
        label = _HEADER_LINE_END.search(line)
        if label is None or index + 1 >= len(lines):
            continue
        following = lines[index + 1].rstrip()
        spans = {(start, end) for start, end, _ in date_spans(following)}
        if len(spans) != 1 or _TABLE_ROW.search(line) or _EVENT.search(f"{line} {following}"):
            return []
        [(start, end)] = spans
        day = _one_date(following, start, end)
        if end != len(following) or day is None or _ANOTHER_DATE.search(following[:start]):
            return []  # not its value, or another date's ("Ihr Schreiben vom 15.02.2026")
        value = following[start:end]
        if words and not _under(words, value):
            return []  # under another column
        alone = line.strip().rstrip(":").strip() == label.group("label") and following.strip() == value
        if not words and not alone:
            return []  # without the page's word boxes: only a label and a date each alone on its line
        phrase = f"{label.group('label')} {value}"
        quote = re.sub(r"\s+", " ", following).strip()  # the page's own words, for the evidence
        statement = _Statement(
            DateSpec(type="none", text=phrase), phrase, following, grounding, letter_date=day, quote=quote
        )
        return [statement]
    return []


def letter_statements(pages: Sequence[PageInput]) -> list[_Statement]:
    """Every deadline statement :func:`find_rivals` can read in the letter, and the dates it gives for
    itself (in its text, and in its first page's header: :func:`_header_date`)."""
    found: list[_Statement] = []
    for index, page in enumerate(pages):
        text, grounding = _page_text(page)
        if index == 0:
            found += _header_date(text, _page_words(page), grounding)
        for clause, dates in _clauses(text):
            found += _explicit(clause, dates, grounding)
            found += _relative(clause, grounding)
            found += _relative_deadline(clause, grounding)
            found += _letter_dates(clause, dates, grounding)
    return found


def _nature(item: ExtractedItem) -> Nature | None:
    if item.date.nature == "objection":
        return "objection"
    if item.kind == "payment" or item.date.nature == "payment":
        return "payment"
    if item.date.nature == "notice":
        return "notice"
    if item.date.nature == "declaration":
        return "declaration"
    return None


def _normalised(text: str) -> str:
    return normalise_with_map(text)[0]


def _is_own(statement: _Statement, item: ExtractedItem) -> bool:
    """Whether the statement is the to-do's own sentence (its quote says it)."""
    phrase = _normalised(statement.phrase)
    return bool(phrase) and phrase in _normalised(item.quote)


def _found(patterns: dict[str, re.Pattern[str]], text: str) -> set[str]:
    return {key for key, pattern in patterns.items() if pattern.search(text)}


def _own_words(item: ExtractedItem) -> str:
    return f"{item.quote} {item.date.text or ''}"


def _other_obligation(statement: _Statement, item: ExtractedItem, others: Sequence[ExtractedItem]) -> bool:
    """Whether the statement dates another to-do of the letter (its date or its period), names an
    amount that is not the to-do's (an instalment, a fee) or a kind of obligation the to-do's own
    sentence does not ("die neuen Abschläge … erstmals am", "die nächste Vorauszahlung ist fällig am"),
    or — for an objection — another remedy than the to-do's (a Klage's date is not a Beschwerde's), for a
    declaration something else to send (the documents' date is not the questionnaire's), for a notice
    another right to cancel (a special right's date is not the ordinary notice's)."""
    if _found(_OTHER_OBLIGATION, statement.context) - _found(_OTHER_OBLIGATION, _own_words(item)):
        return True
    own = f"{_own_words(item)} {item.title}"
    if statement.spec.nature == "objection":
        remedies = _found(_REMEDIES, own)
        if not remedies & _found(_REMEDIES, statement.context):
            return True  # another remedy, or the to-do names none: whether it is the same can't be told
    declared = _found(_DECLARED, statement.context)
    if statement.spec.nature == "declaration" and not _found(_DECLARED, own) & declared:
        # something else to send, or the to-do names nothing: whether it is the same can't be told
        return True
    if statement.spec.nature == "notice" and _found(_NOTICE_KINDS, own) != _found(
        _NOTICE_KINDS, statement.context
    ):
        return True
    spec = statement.spec
    for other in others:
        if other is item or other.date.type == "none":
            continue
        if spec.type == "fixed" and other.date.type == "fixed" and other.date.date == spec.date:
            return True
        if (
            spec.type == "relative"
            and other.date.type == "relative"
            and (other.date.amount, other.date.unit) == (spec.amount, spec.unit)
        ):
            return True
    amounts = parse_amounts(statement.window)
    return item.amount is not None and bool(amounts) and all(abs(a - item.amount) >= 0.005 for a in amounts)


def find_rivals(
    item: ExtractedItem, others: Sequence[ExtractedItem], pages: Sequence[PageInput]
) -> tuple[Rival, ...]:
    """The letter's other statements that date the same obligation as ``item`` (see the module
    docstring); ``others`` are the reading's to-dos, ``item`` among them. Found in the text alone: whether
    a statement's date differs from the to-do's is for :func:`settle` to say."""
    if item.date.type == "none" or item.recurrence is not None or item.direction == "in":
        return ()
    nature = _nature(item)
    if _DISCOUNT.search(item.quote):
        return ()  # its sentence speaks of a discount: which date is the discount's is the reading's to tell
    if nature in _NEW_NATURES and _OPTIONAL.search(item.quote):
        # an optional earlier day ("möglichst bis"): which date must be met is the reading's to tell
        nature = None
    rivals: list[Rival] = []
    for statement in letter_statements(pages):
        if statement.letter_date is not None:
            if item.date.type == "relative":
                rivals.append(
                    Rival(
                        item.date,
                        statement.phrase,
                        statement.grounding,
                        statement.letter_date,
                        statement.quote,
                    )
                )
            continue
        if nature is None or statement.spec.nature != nature or _is_own(statement, item):
            continue
        if _other_obligation(statement, item, others):
            continue
        rivals.append(Rival(statement.spec, statement.phrase, statement.grounding))
    unique = {(rival.spec.model_dump_json(), rival.statement, rival.letter_date): rival for rival in rivals}
    return tuple(unique.values())


def law_rivals(spec: DateSpec, pages: Sequence[PageInput]) -> tuple[Rival, ...]:
    """For a deadline the law adds to the letter (``spec``, :func:`~ordnung.ingest.plan.sync_rule_items`):
    the dates the letter gives for itself, each to count it from (:func:`settle_law`)."""
    rivals = {
        (statement.phrase, statement.letter_date): Rival(
            spec, statement.phrase, statement.grounding, statement.letter_date, statement.quote
        )
        for statement in letter_statements(pages)
        if statement.letter_date is not None
    }
    return tuple(rivals.values())


# --------------------------------------------------------------------------------------------------
# Settling the dates (compute stage)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settled:
    """A to-do's receipt after :func:`settle`: the earlier date kept, both named. ``fixed``: the date
    kept is one the letter writes (not a period the engine counted)."""

    receipt: ComputationReceipt
    fixed: bool


@dataclass(frozen=True)
class _Candidate:
    due: date
    receipt: ComputationReceipt
    statement: str
    fixed: bool
    rival: Rival | None = None


def _short(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= _QUOTE_CHARS else text[: _QUOTE_CHARS - 1].rstrip() + "…"


def _noun(item: ExtractedItem) -> str:
    return {"payment": "payment", "deadline": "deadline", "appointment": "appointment"}.get(item.kind, "date")


def _history(written: date, ctx: RuleContext) -> bool:
    """Whether a date the letter writes can't be a second date to meet: on or before the letter's own
    date (the letter's date itself, or a reminder's original due date) — or, when the letter's date is
    not known, before the day it arrived (or today)."""
    if ctx.document_date is not None:
        return written <= ctx.document_date
    return written < (ctx.received_date or ctx.today)


def _rival_candidate(rival: Rival, own: date, ctx: RuleContext, postal_buffer_days: int) -> _Candidate | None:
    """The date a rival statement gives, computed as the to-do's own is — ``None`` when it gives the
    same date, none, a written date that is history (:func:`_history`), or a date before the letter's own
    as read. A date the letter gives for itself counts only near the one read (:data:`_LETTER_DATE_REACH`):
    a letter is not dated weeks apart — such a date is another's (an old invoice's, the decision a
    Widerspruchsbescheid rules on)."""
    if rival.letter_date is not None:
        if ctx.document_date is None or rival.letter_date == ctx.document_date:
            return None
        if abs((rival.letter_date - ctx.document_date).days) > _LETTER_DATE_REACH:
            return None
        counted = replace(ctx, document_date=rival.letter_date)
    elif rival.notice:
        counted = replace(ctx, quote=rival.statement, letter_kind=None)
    else:
        if rival.spec.type == "relative" and ctx.letter_kind in PAYMENT_DEMAND_KINDS:
            return None  # a reminder's "14 Tage nach Rechnungsdatum" counts from the old invoice's date
        written = parse_date(rival.spec.date)
        if written is not None and _history(written, ctx):
            return None
        counted = replace(ctx, quote=rival.statement)
    receipt = grade_reading(
        compute_due(rival.spec, counted, postal_buffer_days=postal_buffer_days), rival.grounding, ()
    )
    due = parse_date(receipt.due_date)
    if due is None or due == own:
        return None
    if not rival.notice and ctx.document_date is not None and due < ctx.document_date:
        return None
    return _Candidate(due, receipt, rival.statement, rival.spec.type == "fixed", rival)


def rival_due(rival: Rival, own: date, ctx: RuleContext, postal_buffer_days: int) -> date | None:
    """The date ``rival`` gives, computed as :func:`settle` computes it (``None`` when it gives none, the same
    date as ``own``, or one :func:`settle` leaves out)."""
    found = _rival_candidate(rival, own, ctx, postal_buffer_days)
    return found.due if found is not None else None


def _warning(noun: str, own: _Candidate, other: _Candidate, kept: date, ctx: RuleContext) -> str:
    """The warning naming both dates, the earlier first."""
    rival = other.rival
    first, second = sorted((own, other), key=lambda candidate: candidate.due)
    if rival is not None and rival.letter_date is not None and ctx.document_date is not None:
        early, late = sorted((ctx.document_date, rival.letter_date))
        return (
            f"The letter gives two dates for itself: {fmt_date(early)} and {fmt_date(late)} "
            f"(“{_short(rival.statement)}”), so this {noun} is {fmt_date(first.due)} or {fmt_date(second.due)}. "
            + (
                f"We use the earlier one, {fmt_date(kept)} — please check which date applies."
                if kept >= first.due
                # a third date found (the letter's own notice) is earlier than both
                else f"We use the earliest of the dates found, {fmt_date(kept)} — please check which date applies."
            )
        )
    if rival is not None and rival.notice:
        return (
            f"Claude's reading and the letter's own instructions on how to object give two dates for this "
            f"{noun}: {fmt_date(first.due)} (“{_short(first.statement)}”) and {fmt_date(second.due)} "
            f"(“{_short(second.statement)}”). We use the earlier one, {fmt_date(kept)} — please check which date "
            "applies."
        )
    return (
        f"The letter gives two dates for this {noun}: {fmt_date(first.due)} (“{_short(first.statement)}”) "
        f"and {fmt_date(second.due)} (“{_short(second.statement)}”). We use the earlier one, {fmt_date(kept)} "
        "— please check which date applies."
    )


def _step(label: str, day: date | None) -> ComputationStep:
    return ComputationStep(
        label=label,
        date=day.isoformat() if day else None,
        rule_id=CONFLICTING_DATES,
        citation=catalog.citation(CONFLICTING_DATES),
    )


def _lead_step(candidate: _Candidate) -> ComputationStep | None:
    """The step before a rival's own computation, saying where in the letter it comes from."""
    rival = candidate.rival
    if rival is None:
        return None
    if rival.letter_date is not None:
        return _step(
            f"The letter also gives {fmt_date(rival.letter_date)} as its own date (“{_short(rival.statement)}”) "
            "— counted from that date:",
            rival.letter_date,
        )
    return _step(f"The letter also says “{_short(rival.statement)}”:", None)


def _other_step(noun: str, candidate: _Candidate, kept: _Candidate, ctx: RuleContext) -> ComputationStep:
    """The step naming a date the letter gives that is not the one kept."""
    rival = candidate.rival
    if rival is None:  # the to-do's own date, as read
        if (
            kept.rival is not None and kept.rival.notice
        ):  # beside the letter's own notice: the reading's, not the letter's
            return _step(
                f"Claude's reading gives {fmt_date(candidate.due)} (“{_short(candidate.statement)}”)",
                candidate.due,
            )
        if kept.rival is not None and kept.rival.letter_date is not None and ctx.document_date is not None:
            return _step(
                f"Counted from {fmt_date(ctx.document_date)}, the letter's date as read: {fmt_date(candidate.due)}",
                candidate.due,
            )
        return _step(
            f"The date as read from the letter is {fmt_date(candidate.due)} (“{_short(candidate.statement)}”)",
            candidate.due,
        )
    if rival.letter_date is not None:
        return _step(
            f"Counted from {fmt_date(rival.letter_date)}, the date the letter also gives for itself "
            f"(“{_short(rival.statement)}”): {fmt_date(candidate.due)}",
            candidate.due,
        )
    return _step(
        f"The letter also gives {fmt_date(candidate.due)} for this {noun} (“{_short(candidate.statement)}”)",
        candidate.due,
    )


def settle_law(
    receipt: ComputationReceipt,
    spec: DateSpec,
    rivals: Sequence[Rival],
    ctx: RuleContext,
    *,
    postal_buffer_days: int,
) -> Settled | None:
    """:func:`settle` for a deadline the law adds to the letter (``spec``, its ``receipt`` computed in
    ``ctx``) when the letter gives two dates for itself (``rivals``: :func:`law_rivals`): counted from each,
    the earlier date is kept — the law counts it from the letter's date or its arrival, so acting by the
    earlier is on time whichever date the letter really has."""
    item = ExtractedItem(kind="deadline", title="", date=spec, quote="")
    return settle(receipt, item, rivals, ctx, postal_buffer_days=postal_buffer_days, law=True)


def settle(
    receipt: ComputationReceipt,
    item: ExtractedItem,
    rivals: Sequence[Rival],
    ctx: RuleContext,
    *,
    postal_buffer_days: int,
    law: bool = False,
) -> Settled | None:
    """The to-do's receipt when the letter gives it another date (``None`` when it gives none): the
    earliest of the dates kept, with the engine's steps for it, a step per other date and one saying
    why the earlier one is kept, a warning naming both dates, rule ``conflicting_dates`` and ``low``
    confidence. ``receipt`` is the to-do's own (graded), computed in ``ctx``; ``law``: a deadline the
    law adds (:func:`settle_law`)."""
    own_due = parse_date(receipt.due_date)
    if own_due is None or not rivals:
        return None
    own = _Candidate(own_due, receipt, item.date.text or item.quote, item.date.type == "fixed")
    others: list[_Candidate] = []
    for rival in rivals:
        found = _rival_candidate(rival, own_due, ctx, postal_buffer_days)
        if found is not None and all(found.due != seen.due for seen in others):
            others.append(found)
    if not others:
        return None
    noun = _noun(item)
    kept = min([own, *others], key=lambda candidate: candidate.due)
    dates = len({own.due, *(other.due for other in others)})
    count = _COUNTS.get(dates, str(dates))
    lead = _lead_step(kept)
    own_dates = {ctx.document_date, *(other.rival.letter_date for other in others if other.rival is not None)}
    # the letter's own notice set beside the reading's date: the other date is the reading's, not the letter's
    noticed = any(other.rival is not None and other.rival.notice for other in others)
    source = (
        "Claude's reading and the letter's own instructions on how to object give"
        if noticed
        else "The letter gives"
    )
    why = (
        f"The law counts this deadline from the letter's date or its arrival, and the letter gives "
        f"{_COUNTS.get(len(own_dates), str(len(own_dates)))} dates for itself: we keep the earliest, "
        f"{fmt_date(kept.due)} — acting by it is on time whichever date the letter really has"
        if law
        else f"{source} {count} different dates for this {noun}: we keep the earliest, "
        f"{fmt_date(kept.due)} — acting by it is on time whichever date applies"
    )
    steps = [
        *([lead] if lead is not None else []),
        *kept.receipt.steps,
        *(_other_step(noun, other, kept, ctx) for other in [own, *others] if other is not kept),
        _step(why, kept.due),
    ]
    warnings = [_warning(noun, own, other, kept.due, ctx) for other in others]
    later = ", ".join(fmt_date(c.due) for c in sorted([own, *others], key=lambda c: c.due) if c is not kept)
    also = (
        "Claude's reading also gives"
        if noticed and len(others) == 1 and kept is not own
        else "The letter also gives"
    )
    summary = f"{kept.receipt.summary} {also} {later}; this is the earlier date.".strip()
    rule_ids = [
        *kept.receipt.rule_ids,
        *([] if CONFLICTING_DATES in kept.receipt.rule_ids else [CONFLICTING_DATES]),
    ]
    settled = kept.receipt.model_copy(
        update={
            "steps": steps,
            "rule_ids": rule_ids,
            "warnings": [*kept.receipt.warnings, *warnings],
            "summary": summary,
            "confidence": "low",
        }
    )
    return Settled(settled, kept.fixed)
