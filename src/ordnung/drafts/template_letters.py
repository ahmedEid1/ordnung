"""Everyday letters written entirely from fixed templates (SPEC §11, §21, ADR 0006).

Each letter asks for something — a withdrawal, more time, instalments, a repair, your data, the
receipts behind a statement, the deposit back, or notes a new address. The sentences that do
something legally come only from here, in German (the letter) and English (the reference
translation); the model may add a polite paragraph and the translation, never these sentences.

Inputs come from the ledger (the letter or contract the letter is about, the profile) and from
:class:`~ordnung.models.LetterDetails`, which the person fills in. :data:`TEMPLATES` names what each
letter requires; a missing optional fact is left out of the sentence, except the account number of
a deposit letter, which is left as the placeholder ``[IBAN]`` so the checks ask for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ordnung.drafts.templates import LetterLanguage, LetterParts, closing, format_date, salutation
from ordnung.models import LetterDetails, TemplateDraftKind

IBAN_PLACEHOLDER = "[IBAN]"


class TemplateError(ValueError):
    """A template letter can't be written from these facts; the message says what to add."""


@dataclass(frozen=True)
class TemplateSpec:
    """What a template letter is (for the model's context) and which facts it requires."""

    label: str
    required: tuple[str, ...] = ()


#: Every template letter, with the :class:`~ordnung.models.LetterDetails` fields it requires.
TEMPLATES: dict[str, TemplateSpec] = {
    "withdrawal": TemplateSpec("withdrawal from a contract (Widerruf)", ("subject_matter",)),
    "extension_request": TemplateSpec("request for more time (Fristverlängerung)", ("until",)),
    "payment_plan": TemplateSpec(
        "request to pay in instalments or defer a payment (Ratenzahlung/Stundung)",
        ("instalment", "first_instalment"),
    ),
    "defect_notice": TemplateSpec("notice of a defect to the landlord (Mängelanzeige)", ("defect",)),
    "data_access": TemplateSpec("request for access to personal data (Art. 15 GDPR)"),
    "receipts_inspection": TemplateSpec("request to inspect the receipts of an operating-cost statement"),
    "deposit_return": TemplateSpec("request to return the rent deposit (Mietkaution)", ("moved_out_on",)),
    "address_change": TemplateSpec("notice of a new address", ("new_address",)),
}

_FIELD_NAMES = {
    "subject_matter": "what you ordered or agreed to",
    "until": "the new date you ask for",
    "instalment": "the monthly instalment you offer",
    "first_instalment": "the day of the first instalment",
    "defect": "what is broken or wrong",
    "moved_out_on": "the day you handed the flat back",
    "new_address": "your new address",
}


@dataclass(frozen=True)
class TemplateInput:
    """Everything a template letter can use: the person's details and what the ledger knows.

    ``topic`` is the contract's name or the letter's title; ``address`` the person's address from the
    profile; ``deadline``, ``amount`` and ``period`` are the letter's earliest open deadline, its
    payment and its billing period, used when the person gave none.
    """

    details: LetterDetails
    reference: str | None = None
    doc_date: date | None = None
    topic: str | None = None
    address: str | None = None
    iban: str | None = None
    person_name: str | None = None
    tax_office: bool = False
    schufa: bool = False
    deadline: date | None = None
    amount: float | None = None
    period: str | None = None


def _day(value: str | None, what: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise TemplateError(f"“{value}” is not a date — check {what}.") from None


def format_money(amount: float, language: LetterLanguage) -> str:
    """``1.234,56 €`` in German letters, ``€1,234.56`` in English."""
    english = f"{amount:,.2f}"
    if language == "en":
        return f"€{english}"
    return english.replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def _one_line(address: str | None) -> str | None:
    if not address:
        return None
    parts = [part.strip() for line in address.splitlines() for part in line.split(",") if part.strip()]
    return ", ".join(parts) or None


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _dash(*parts: str | None) -> str:
    return " – ".join(part for part in parts if part)


def missing_facts(kind: str, inp: TemplateInput) -> list[str]:
    """What the person still has to give for a ``kind`` letter (plain English), empty when complete."""
    known = {
        "subject_matter": inp.details.subject_matter or inp.topic,
        "new_address": inp.details.new_address or inp.address,
    }
    missing = []
    for name in TEMPLATES[kind].required:
        value = known.get(name, getattr(inp.details, name))
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(_FIELD_NAMES[name])
    return missing


# --------------------------------------------------------------------------------------------------
# the letters
# --------------------------------------------------------------------------------------------------


def _withdrawal(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    what = (inp.details.subject_matter or inp.topic or "").strip()
    ordered = _day(inp.details.ordered_on, "the order date")
    received = _day(inp.details.received_on, "the delivery date")
    if language == "de":
        when = ", ".join(
            part
            for part in (
                f"bestellt am {format_date(ordered, language)}" if ordered else None,
                f"erhalten am {format_date(received, language)}" if received else None,
            )
            if part
        )
        operative = f"hiermit widerrufe ich den von mir abgeschlossenen Vertrag über „{what}“{f' ({when})' if when else ''}."
        refund = (
            "Bitte bestätigen Sie mir den Eingang dieses Widerrufs und erstatten Sie mir alle Zahlungen, die "
            "ich geleistet habe."
        )
        subject = _dash(f"Widerruf des Vertrags über „{what}“", inp.reference)
    else:
        when = ", ".join(
            part
            for part in (
                f"ordered on {format_date(ordered, language)}" if ordered else None,
                f"received on {format_date(received, language)}" if received else None,
            )
            if part
        )
        operative = (
            f"I hereby withdraw from the contract I concluded for “{what}”{f' ({when})' if when else ''}."
        )
        refund = "Please confirm receipt of this withdrawal and refund all payments I have made."
        subject = _dash(f"Withdrawal from the contract for “{what}”", inp.reference)
    return LetterParts(subject, salutation(language, inp.person_name), (operative, refund), closing(language))


def _extension(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    until = _day(inp.details.until, "the new date")
    assert until is not None  # required (missing_facts)
    deadline = _day(inp.details.deadline, "the current deadline") or inp.deadline
    if deadline is not None and until <= deadline:
        raise TemplateError("The new date must be later than the current deadline.")
    if language == "de":
        lead = (
            f"zu Ihrem Schreiben vom {format_date(inp.doc_date, language)} "
            if inp.doc_date
            else "in dieser Angelegenheit "
        )
        set_until = f"bis zum {format_date(deadline, language)} gesetzte" if deadline else "gesetzte"
        operative = f"{lead}bitte ich Sie, die mir {set_until} Frist bis zum {format_date(until, language)} zu verlängern."
        confirm = "Bitte bestätigen Sie mir die Verlängerung kurz schriftlich."
        about = f"Ihr Schreiben vom {format_date(inp.doc_date, language)}" if inp.doc_date else None
        subject = _dash("Bitte um Fristverlängerung", about, inp.reference)
    else:
        lead = f"Regarding your letter of {format_date(inp.doc_date, language)}, " if inp.doc_date else ""
        current = f" for {format_date(deadline, language)}" if deadline else ""
        operative = f"{lead}I kindly ask you to extend the deadline you set me{current} until {format_date(until, language)}."
        confirm = "Please briefly confirm the extension in writing."
        about = f"Your letter of {format_date(inp.doc_date, language)}" if inp.doc_date else None
        subject = _dash("Request for an extension of the deadline", about, inp.reference)
    return LetterParts(
        subject, salutation(language, inp.person_name), (operative, confirm), closing(language)
    )


def _payment_plan(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    instalment = inp.details.instalment
    first = _day(inp.details.first_instalment, "the first instalment")
    assert instalment is not None and first is not None  # required (missing_facts)
    amount = inp.details.amount if inp.details.amount is not None else inp.amount
    if amount is not None and instalment > amount:
        raise TemplateError("The monthly instalment can't be more than the amount you owe.")
    rate = format_money(instalment, language)
    start = format_date(first, language)
    if language == "de":
        total = f" in Höhe von {format_money(amount, language)}" if amount is not None else ""
        offer = f"den Betrag in monatlichen Raten von {rate} zu zahlen, beginnend am {start}."
        if inp.tax_office:
            dated = f" mit Bescheid vom {format_date(inp.doc_date, language)}" if inp.doc_date else ""
            paragraphs: tuple[str, ...] = (
                f"hiermit beantrage ich die Stundung der{dated} festgesetzten Steuer{total} nach § 222 AO.",
                f"Ich biete an, {offer}",
                "Die sofortige Zahlung des vollen Betrags wäre für mich eine erhebliche Härte.",
            )
            subject = _dash("Antrag auf Stundung nach § 222 AO", inp.reference)
        else:
            dated = f" aus Ihrem Schreiben vom {format_date(inp.doc_date, language)}" if inp.doc_date else ""
            paragraphs = (
                f"zu Ihrer Forderung{dated}{total} biete ich Ihnen an, {offer}",
                "Bitte bestätigen Sie mir die Ratenzahlung schriftlich.",
            )
            subject = _dash("Bitte um Ratenzahlung", inp.reference)
    else:
        total = f" of {format_money(amount, language)}" if amount is not None else ""
        offer = f"to pay the amount in monthly instalments of {rate}, starting on {start}."
        if inp.tax_office:
            dated = (
                f" assessed by the notice of {format_date(inp.doc_date, language)}" if inp.doc_date else ""
            )
            paragraphs = (
                f"I hereby apply for a deferral (Stundung) of the tax{total}{dated} under § 222 AO.",
                f"I offer {offer}",
                "Paying the full amount at once would be a considerable hardship for me.",
            )
            subject = _dash("Application for deferral under § 222 AO", inp.reference)
        else:
            dated = f" in your letter of {format_date(inp.doc_date, language)}" if inp.doc_date else ""
            paragraphs = (
                f"Regarding your claim{total}{dated}, I offer {offer}",
                "Please confirm the instalment plan in writing.",
            )
            subject = _dash("Request to pay in instalments", inp.reference)
    return LetterParts(subject, salutation(language, inp.person_name), paragraphs, closing(language))


def _defect(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    defect = _sentence(inp.details.defect or "")
    since = _day(inp.details.noticed_on, "since when the defect exists")
    fix_by = _day(inp.details.fix_by, "the repair date")
    flat = _one_line(inp.address)
    if language == "de":
        paragraphs = [
            f"hiermit zeige ich Ihnen einen Mangel in meiner Wohnung{f' {flat}' if flat else ''} an: {defect}"
        ]
        if since:
            paragraphs.append(f"Der Mangel besteht seit dem {format_date(since, language)}.")
        paragraphs.append(
            f"Bitte beseitigen Sie den Mangel bis zum {format_date(fix_by, language)}."
            if fix_by
            else "Bitte beseitigen Sie den Mangel umgehend."
        )
        paragraphs.append("Bis zur Beseitigung behalte ich mir vor, die Miete zu mindern.")
        subject = _dash("Mängelanzeige", f"Wohnung {flat}" if flat else None, inp.reference)
    else:
        paragraphs = [f"I hereby notify you of a defect in my flat{f' at {flat}' if flat else ''}: {defect}"]
        if since:
            paragraphs.append(f"The defect has existed since {format_date(since, language)}.")
        paragraphs.append(
            f"Please repair it by {format_date(fix_by, language)}."
            if fix_by
            else "Please repair it without delay."
        )
        paragraphs.append("Until it is repaired, I reserve the right to reduce the rent.")
        subject = _dash("Notice of a defect", f"flat at {flat}" if flat else None, inp.reference)
    return LetterParts(subject, salutation(language, inp.person_name), tuple(paragraphs), closing(language))


def _data_access(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    if language == "de":
        paragraphs = [
            "hiermit bitte ich Sie um Auskunft nach Art. 15 DSGVO, ob Sie personenbezogene Daten über mich verarbeiten.",
            "Falls ja, bitte ich um Auskunft über diese Daten, die Zwecke der Verarbeitung, die Empfänger, die "
            "geplante Speicherdauer und die Herkunft der Daten (Art. 15 Abs. 1 DSGVO) sowie um eine kostenlose "
            "Kopie der Daten (Art. 15 Abs. 3 DSGVO).",
        ]
        if inp.schufa:
            paragraphs.append(
                "Dazu gehören auch die zu meiner Person gespeicherten und übermittelten Scorewerte."
            )
        paragraphs.append(
            "Bitte antworten Sie innerhalb eines Monats nach Eingang dieses Schreibens (Art. 12 Abs. 3 DSGVO)."
        )
        subject = _dash("Auskunftsersuchen nach Art. 15 DSGVO", inp.reference)
    else:
        paragraphs = [
            "I hereby request access under Art. 15 GDPR: please confirm whether you process personal data about me.",
            "If so, please tell me what data you hold, the purposes of processing, the recipients, how long it will "
            "be stored and where it came from (Art. 15(1) GDPR), and send me a free copy of the data (Art. 15(3) GDPR).",
        ]
        if inp.schufa:
            paragraphs.append("This includes the score values stored about me and passed on to others.")
        paragraphs.append("Please reply within one month of receiving this letter (Art. 12(3) GDPR).")
        subject = _dash("Request for access under Art. 15 GDPR", inp.reference)
    return LetterParts(subject, salutation(language, inp.person_name), tuple(paragraphs), closing(language))


def _receipts(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    period = (inp.details.period or inp.period or "").strip()
    if language == "de":
        dated = f" vom {format_date(inp.doc_date, language)}" if inp.doc_date else ""
        span = f" für den Abrechnungszeitraum {period}" if period else ""
        paragraphs: tuple[str, ...] = (
            f"zu Ihrer Betriebskostenabrechnung{dated}{span} bitte ich um Einsicht in die Abrechnungsbelege "
            "(§ 556 Abs. 4 BGB).",
            "Bitte teilen Sie mir mit, wann und wo ich die Belege einsehen kann, oder stellen Sie sie mir "
            "elektronisch zur Verfügung.",
            "Einwendungen gegen die Abrechnung behalte ich mir vor.",
        )
        subject = _dash(f"Belegeinsicht zur Betriebskostenabrechnung{dated}", inp.reference)
    else:
        dated = f" of {format_date(inp.doc_date, language)}" if inp.doc_date else ""
        span = f" for the billing period {period}" if period else ""
        paragraphs = (
            f"Regarding your operating-cost statement{dated}{span}, I ask to inspect the receipts it is based on "
            "(§ 556 Abs. 4 BGB).",
            "Please let me know when and where I can see them, or make them available to me electronically.",
            "I reserve the right to object to the statement.",
        )
        subject = _dash(f"Inspection of the receipts for the operating-cost statement{dated}", inp.reference)
    return LetterParts(subject, salutation(language, inp.person_name), paragraphs, closing(language))


def _deposit(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    returned = _day(inp.details.moved_out_on, "the day you handed the flat back")
    assert returned is not None  # required (missing_facts)
    flat = _one_line(inp.details.old_address)
    iban = (inp.iban or "").replace(" ", "") or IBAN_PLACEHOLDER
    amount = inp.details.amount
    if language == "de":
        total = f" in Höhe von {format_money(amount, language)}" if amount is not None else ""
        paragraphs: tuple[str, ...] = (
            f"das Mietverhältnis über die Wohnung{f' {flat}' if flat else ''} ist beendet; die Wohnung habe ich am "
            f"{format_date(returned, language)} an Sie zurückgegeben.",
            f"Bitte rechnen Sie über die Mietkaution{total} ab und überweisen Sie mir das Guthaben einschließlich "
            f"der Zinsen auf mein Konto mit der IBAN {iban}.",
            "Bitte teilen Sie mir mit, bis wann ich mit der Abrechnung rechnen kann.",
        )
        subject = _dash("Rückzahlung der Mietkaution", f"Wohnung {flat}" if flat else None, inp.reference)
    else:
        total = f" of {format_money(amount, language)}" if amount is not None else ""
        paragraphs = (
            f"The tenancy of the flat{f' at {flat}' if flat else ''} has ended; I handed the flat back to you on "
            f"{format_date(returned, language)}.",
            f"Please settle the rent deposit{total} and transfer the balance, including interest, to my account "
            f"with the IBAN {iban}.",
            "Please let me know when I can expect the settlement.",
        )
        subject = _dash("Return of the rent deposit", f"flat at {flat}" if flat else None, inp.reference)
    return LetterParts(subject, salutation(language, inp.person_name), paragraphs, closing(language))


def _address(language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    new = _one_line(inp.details.new_address or inp.address)
    old = _one_line(inp.details.old_address)
    moved = _day(inp.details.moved_on, "the day of the move")
    if language == "de":
        paragraphs = [
            f"bitte beachten Sie, dass sich meine Anschrift{f' zum {format_date(moved, language)}' if moved else ''} "
            "geändert hat.",
            f"Meine neue Anschrift lautet: {new}.",
        ]
        if old:
            paragraphs.append(f"Meine bisherige Anschrift war: {old}.")
        paragraphs.append("Bitte senden Sie Ihre Post künftig an meine neue Anschrift.")
        subject = _dash("Änderung meiner Anschrift", inp.reference)
    else:
        paragraphs = [
            f"Please note that my address has changed{f' as of {format_date(moved, language)}' if moved else ''}.",
            f"My new address is: {new}.",
        ]
        if old:
            paragraphs.append(f"My previous address was: {old}.")
        paragraphs.append("Please send your post to my new address from now on.")
        subject = _dash("Change of address", inp.reference)
    return LetterParts(subject, salutation(language, inp.person_name), tuple(paragraphs), closing(language))


#: Where the sentences above write an address (the flat, the new and the old address), so a stored letter's
#: addresses can be kept from the model when it is translated again (``compose.letter_private_values``).
ADDRESS_FRAMES = re.compile(
    r"(?:meiner Wohnung|über die Wohnung|in my flat at|of the flat at) (?P<address>[^\n]+?)"
    r"(?= an:| ist beendet;| has ended;|: )|"
    r"(?:Anschrift lautet|Anschrift war|new address is|previous address was): (?P<line>[^\n]+?)\.?$|"
    r"– (?:Wohnung|flat at) (?P<subject>[^\n–]+?)(?= –|$)",
    re.M,
)


_BUILDERS = {
    "withdrawal": _withdrawal,
    "extension_request": _extension,
    "payment_plan": _payment_plan,
    "defect_notice": _defect,
    "data_access": _data_access,
    "receipts_inspection": _receipts,
    "deposit_return": _deposit,
    "address_change": _address,
}


def template_letter(kind: TemplateDraftKind, language: LetterLanguage, inp: TemplateInput) -> LetterParts:
    """The fixed frame of a ``kind`` letter; raises :class:`TemplateError` when a required fact is missing
    or a given one is invalid."""
    missing = missing_facts(kind, inp)
    if missing:
        raise TemplateError(f"To write this letter, add {' and '.join(missing)}.")
    return _BUILDERS[kind](language, inp)
