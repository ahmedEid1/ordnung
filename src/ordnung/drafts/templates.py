"""Fixed, legally operative letter text (SPEC §11, §21).

The sentences that *do* something legally — the cancellation, the objection, the request to confirm
receipt — come only from these templates, never from a model. Every template exists in German (the
letter) and in English (the reference translation shown next to it and used when no model is
available). The model may add polite free text and a translation; it never writes these sentences.

Salutation and closing follow German business-letter practice: "Sehr geehrte Damen und Herren," for
organisations, the gender-neutral "Guten Tag <Name>," for a named person, and "Mit freundlichen
Grüßen" (no comma) as the closing formula.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

LetterLanguage = Literal["de", "en"]
RemedyKind = Literal["einspruch", "widerspruch"]
LETTER_LANGUAGES: tuple[LetterLanguage, ...] = ("de", "en")

#: Placeholder put into an empty general reply so the ``no_placeholders`` check asks the person to write it.
BODY_PLACEHOLDER: dict[LetterLanguage, str] = {"de": "[Ihr Text]", "en": "[Your text]"}

_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_REMEDY_DE: dict[RemedyKind, str] = {"einspruch": "Einspruch", "widerspruch": "Widerspruch"}
_REMEDY_EN: dict[RemedyKind, str] = {
    "einspruch": "an objection (Einspruch)",
    "widerspruch": "an objection (Widerspruch)",
}
_REMEDY_SUBJECT_EN: dict[RemedyKind, str] = {
    "einspruch": "Objection (Einspruch)",
    "widerspruch": "Objection (Widerspruch)",
}
# German noun (masculine: "gegen den …") and English equivalent of the challenged decision.
_DECISIONS: dict[str, tuple[str, str]] = {
    "tax_assessment": ("Steuerbescheid", "tax assessment"),
    "fine": ("Bußgeldbescheid", "fine notice"),
    "court_payment_order": ("Mahnbescheid", "court payment order (Mahnbescheid)"),
    "enforcement_order": ("Vollstreckungsbescheid", "enforcement order (Vollstreckungsbescheid)"),
}
#: The remedy the law gives a letter kind, whatever its instructions say (§ 694, § 700 ZPO; § 574 BGB).
STATUTORY_REMEDIES: dict[str, RemedyKind] = {
    "court_payment_order": "widerspruch",
    "enforcement_order": "einspruch",
    "landlord_notice": "widerspruch",
}
_DEFAULT_DECISION = ("Bescheid", "decision")


@dataclass(frozen=True)
class LetterParts:
    """The code-written frame of a letter: subject, salutation, operative paragraphs and closing."""

    subject: str
    salutation: str
    paragraphs: tuple[str, ...]
    closing: str


def format_date(day: date, language: LetterLanguage) -> str:
    """``31.12.2026`` in German letters (DIN 5008), ``31 December 2026`` in English."""
    if language == "de":
        return day.strftime("%d.%m.%Y")
    return f"{day.day} {_MONTHS_EN[day.month - 1]} {day.year}"


def salutation(language: LetterLanguage, person_name: str | None = None) -> str:
    """Opening line: to an organisation, or to a named person (gender-neutral in German)."""
    if person_name:
        return f"Guten Tag {person_name}," if language == "de" else f"Dear {person_name},"
    return "Sehr geehrte Damen und Herren," if language == "de" else "Dear Sir or Madam,"


def closing(language: LetterLanguage) -> str:
    """Closing formula (German without a trailing comma, as in DIN 5008)."""
    return "Mit freundlichen Grüßen" if language == "de" else "Yours faithfully"


def decision_noun(document_kind: str | None, language: LetterLanguage) -> str:
    """What the challenged letter is called: ``Steuerbescheid`` / ``tax assessment`` / ``Bescheid``."""
    german, english = _DECISIONS.get(document_kind or "", _DEFAULT_DECISION)
    return german if language == "de" else english


def remedy_label(remedy: RemedyKind, language: LetterLanguage) -> str:
    """``Einspruch`` / ``an objection (Einspruch)``."""
    return _REMEDY_DE[remedy] if language == "de" else _REMEDY_EN[remedy]


def _join(*parts: str | None) -> str:
    return ", ".join(part for part in parts if part)


def _dash(*parts: str | None) -> str:
    return " – ".join(part for part in parts if part)


def cancellation(
    language: LetterLanguage,
    *,
    contract_name: str,
    customer_number: str | None,
    end_date: date | None,
    person_name: str | None = None,
) -> LetterParts:
    """Notice of cancellation "fristgerecht zum <end date>, hilfsweise zum nächstmöglichen Zeitpunkt".

    Without a known end date the notice is given "zum nächstmöglichen Zeitpunkt" only; without a
    customer number that part is left out.
    """
    if language == "de":
        number = f"Kundennummer {customer_number}" if customer_number else None
        when = (
            f"fristgerecht zum {format_date(end_date, language)}, hilfsweise zum nächstmöglichen Zeitpunkt"
            if end_date
            else "zum nächstmöglichen Zeitpunkt"
        )
        operative = f"hiermit kündige ich den Vertrag „{contract_name}“, {_join(number, when)}."
        confirm = (
            "Bitte bestätigen Sie mir den Eingang dieser Kündigung sowie das Beendigungsdatum schriftlich."
        )
        subject = _dash(f"Kündigung des Vertrags „{contract_name}“", number)
    else:
        number = f"customer number {customer_number}" if customer_number else None
        when = (
            f"with due notice effective {format_date(end_date, language)}, or alternatively at the "
            "earliest possible date"
            if end_date
            else "at the earliest possible date"
        )
        operative = (
            f"I hereby give notice to terminate the contract “{contract_name}”, {_join(number, when)}."
        )
        confirm = (
            "Please confirm in writing that you have received this notice and the date on which the "
            "contract ends."
        )
        subject = _dash(f"Cancellation of the contract “{contract_name}”", number)
    return LetterParts(subject, salutation(language, person_name), (operative, confirm), closing(language))


# The second sentence (reasons) and the application to suspend enforcement, per kind of decision:
# a Widerspruch against a court payment order needs no reasons and objects to the whole claim (a
# partial objection is made on the court's form), and there is nothing to suspend yet; an
# enforcement order is suspended by the court (einstweilige Einstellung, §§ 719, 707 ZPO), a tax or
# administrative decision by the authority (Aussetzung der Vollziehung).
_REASONS: dict[str, tuple[str, str]] = {
    "court_payment_order": (
        "Ich widerspreche dem geltend gemachten Anspruch insgesamt.",
        "I object to the entire claim.",
    ),
}
_DEFAULT_REASONS = ("Eine Begründung reiche ich nach.", "I will submit the reasons separately.")
_SUSPEND: dict[str, tuple[str, str] | None] = {
    "court_payment_order": None,
    "enforcement_order": (
        "Ich beantrage, die Zwangsvollstreckung aus dem Vollstreckungsbescheid einstweilen einzustellen.",
        "I apply for enforcement of the order to be suspended for the time being (einstweilige Einstellung).",
    ),
}
_DEFAULT_SUSPEND = (
    "Ich beantrage die Aussetzung der Vollziehung.",
    "I apply for suspension of enforcement (Aussetzung der Vollziehung).",
)


def objection(
    language: LetterLanguage,
    *,
    remedy: RemedyKind,
    document_kind: str | None,
    doc_date: date | None,
    reference: str | None,
    suspend_enforcement: bool = False,
    person_name: str | None = None,
    flat: str | None = None,
) -> LetterParts:
    """Objection (Einspruch/Widerspruch) "…lege ich gegen den <Bescheid> vom <date>, <ref>, <remedy> ein."

    Reasons are announced for later ("Eine Begründung reiche ich nach."), except against a court
    payment order, which needs none: the letter objects to the whole claim. The application to suspend
    enforcement is added only when the person asks for it, and never against a court payment order,
    which can't be enforced yet. A landlord's notice gets the tenant's objection
    (:func:`tenancy_objection`, ``flat`` is the flat's address).
    """
    if document_kind == "landlord_notice":
        return tenancy_objection(
            language, doc_date=doc_date, reference=reference, flat=flat, person_name=person_name
        )
    decision = decision_noun(document_kind, language)
    reasons = _REASONS.get(document_kind or "", _DEFAULT_REASONS)
    suspend = _SUSPEND.get(document_kind or "", _DEFAULT_SUSPEND)
    if language == "de":
        dated = f"vom {format_date(doc_date, language)}" if doc_date else None
        target = " ".join(part for part in (f"gegen den {decision}", dated) if part)
        target = f"{target}, {reference}," if reference else target
        operative = f"hiermit lege ich {target} {remedy_label(remedy, language)} ein."
        paragraphs = [operative, reasons[0]]
        if suspend_enforcement and suspend is not None:
            paragraphs.append(suspend[0])
        subject = _dash(
            " ".join(part for part in (f"{_REMEDY_DE[remedy]} gegen den {decision}", dated) if part),
            reference,
        )
    else:
        dated = f"of {format_date(doc_date, language)}" if doc_date else None
        target = " ".join(part for part in (f"against the {decision}", dated) if part)
        operative = f"I hereby lodge {remedy_label(remedy, language)} {_join(target, reference)}."
        paragraphs = [operative, reasons[1]]
        if suspend_enforcement and suspend is not None:
            paragraphs.append(suspend[1])
        subject = _dash(
            " ".join(
                part for part in (f"{_REMEDY_SUBJECT_EN[remedy]} against the {decision}", dated) if part
            ),
            reference,
        )
    return LetterParts(subject, salutation(language, person_name), tuple(paragraphs), closing(language))


def tenancy_objection(
    language: LetterLanguage,
    *,
    doc_date: date | None,
    reference: str | None,
    flat: str | None,
    person_name: str | None = None,
) -> LetterParts:
    """The tenant's objection to a landlord's notice asking to stay (§§ 574, 574b BGB).

    Reasons are not required; they follow on request (§ 574b Abs. 1 S. 2 BGB), so the letter offers them.
    """
    if language == "de":
        about = f" über die Wohnung {flat}" if flat else ""
        dated = f" vom {format_date(doc_date, language)}" if doc_date else ""
        operative = (
            f"hiermit widerspreche ich Ihrer Kündigung{dated} des Mietverhältnisses{about} und verlange "
            "die Fortsetzung des Mietverhältnisses (§ 574 BGB)."
        )
        reasons = "Die Gründe teile ich Ihnen auf Wunsch gesondert mit."
        subject = _dash(f"Widerspruch gegen Ihre Kündigung{dated}", reference)
    else:
        about = f" of the flat at {flat}" if flat else ""
        dated = f" of {format_date(doc_date, language)}" if doc_date else ""
        operative = (
            f"I hereby object to your notice{dated} terminating the tenancy{about} and request that the "
            "tenancy be continued (§ 574 BGB)."
        )
        reasons = "I will give you my reasons separately on request."
        subject = _dash(f"Objection to your notice{dated}", reference)
    return LetterParts(subject, salutation(language, person_name), (operative, reasons), closing(language))


def general_reply(
    language: LetterLanguage,
    *,
    doc_date: date | None,
    reference: str | None,
    topic: str | None = None,
    person_name: str | None = None,
) -> LetterParts:
    """A reply: the subject names their letter (or the contract) and the reference; the body is free text.

    ``topic`` (e.g. a contract name) is used when there is no letter to refer to. The subject is empty
    when there is neither, so the caller can supply one.
    """
    if language == "de":
        about = f"Ihr Schreiben vom {format_date(doc_date, language)}" if doc_date else None
        if about is None and topic:
            about = f"Vertrag „{topic}“"
    else:
        about = f"Your letter of {format_date(doc_date, language)}" if doc_date else None
        if about is None and topic:
            about = f"Contract “{topic}”"
    return LetterParts(_dash(about, reference), salutation(language, person_name), (), closing(language))
