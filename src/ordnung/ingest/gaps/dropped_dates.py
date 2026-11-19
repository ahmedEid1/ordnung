"""Dates the letter's own words set that the reading left out, and their to-dos (``check:deadline``)."""

from __future__ import annotations

import bisect
import re
from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal, NamedTuple

from ordnung import clock
from ordnung.ingest.conflicts import _SALUTATION, _clauses, find_rivals, sentences
from ordnung.ingest.gaps.reading import (
    _REMEDY,
    DEADLINE_SLOT,
    DEADLINE_WARNING_PREFIX,
    QUOTE_CAP,
    _empty,
    _flat,
    _visible,
    letter_date,
)
from ordnung.ingest.normalize import fold_punctuation
from ordnung.ingest.verify import PageInput, date_spans
from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem
from ordnung.rules import RuleContext
from ordnung.rules.deadlines import parse_date as _iso

# --------------------------------------------------------------------------------------------------
# An explicit date the letter sets that the reading left out (check:deadline)
# --------------------------------------------------------------------------------------------------

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
    ctx = RuleContext(today=today or written or clock.today(), document_date=written)
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
    am:", "Due date:") or a second-person or imperative verb sets ("Bitte überweisen Sie … bis zum …", "… ist bis zum …
    zu zahlen", "ist am … fällig", "Bitte reichen Sie … bis zum … ein", "… bis spätestens … vorzulegen", "please pay /
    submit … by …": :func:`_deadline_kind`) — never in a sentence that names a remedy (the check of
    :func:`~ordnung.ingest.gaps.reading.check_item` is for those), a condition, something past or already done, the
    sender's own act or a direct debit, an appointment, a discount or a preference, a validity, or an option the person
    may take (:data:`_NOT_OWED`, a request right after a question offering one: :data:`_OPTION_ASKED`); never a period's
    end (:data:`_PERIOD_END`); never the letter's own date or one before it, nor one already past on ``today`` (the day
    the letter arrived or is read: never an overdue to-do from code); and only when no dated to-do of the reading falls
    within :data:`DEADLINE_REACH` days of it, none quotes a sentence with that date (the reading read it), and it is no
    later occurrence of a recurring to-do of the reading (:func:`_series_days`, :func:`_undated_series`). A payment's
    label or "fällig" sets none on a letter that collects by direct debit, is paid or a credit note, or pays out
    (:func:`_not_owed_by_label`), nor does the full price beside a reading's payment dated by its discount
    (:data:`_FULL_PRICE`); and no payment comes back that a reading's warning doubts (:data:`_PAY_DOUBT`).

    Since 2026-10-07 (ADR 0015), beside them and guarded more (:func:`_looser_dates`): a date with its year in a
    looser wording that asks the person in its own words at its sentence's start, or in a label on a page that asks her
    for its kind — at most one of each kind, only for a kind neither the reading's dated to-dos nor a strict date of the
    letter still to come covers. A date without its year files nothing, as before.

    At most :data:`DEADLINE_MAX`, the strict ones first, the earliest. Each is ``low`` and "Please check"
    (:data:`~ordnung.ingest.verify.DEADLINE_LEFT_OUT`), worded as a cross-check of the letter, its quote the letter's
    own line or sentence, its date the one the letter writes (never moved: ``shift_rule="none"``). None for an almost
    blank reading (its own to-do sends the person to the letter: :func:`~ordnung.ingest.gaps.reading.check_item`) or
    one that calls the letter a scam (a payment it rightly left out is never brought back)."""
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
