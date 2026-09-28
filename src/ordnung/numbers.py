"""My numbers: every number a form, portal or hotline asks for, sorted by whose it is — pure code, no I/O.

Letters carry two kinds of numbers side by side: the person's own (a Steuer-ID on a payslip, a customer
number on a bill) and the sender's registry numbers (its USt-IdNr., HRB, Gläubiger-ID). The model reads
them all into ``Document.references`` and the sender's identifiers; this module sorts them with one short
written policy (ADR 0007). Tests pin every rule; cases it does not decide are limitations, listed below.

**Where numbers come from.** Only live letters without scam signs: their references, the sender's
identifiers in their stored reading, and the IBAN a letter gives for payment (always where to pay the
sender — the person's own account only when it is the profile's IBAN — whatever the payee is called). A
number lives as long as a letter that shows it (the party's merged identifier list is not read: it
outlives deleted letters). A letter with scam signs contributes nothing — its numbers are the sender's
claims.

**What a number is** (:func:`classify`; the first rule that matches decides). A label *names a matter*
when it says the number is a case reference or one of yours with the organisation (customer, contract,
order, Aktenzeichen, "Ihr Zeichen" …, not an account); such a label wins over the value's look.

1. *Not a number*: a value without a digit, or with a word in small letters ("Nr. 05-2-03, 2. OG links"
   is a description of a flat).
2. *By its shape* — a German creditor identifier (``DE98ZZZ09999999999``) is the organisation's
   Gläubiger-ID and ``DE`` + nine digits its USt-IdNr. (unless the label names a matter: a
   "Kundennummer DE123456789" is a customer number); an IBAN — a valid one, or one that fails only its
   check digits or stands under an IBAN label (a misread IBAN, which then "does not check"; not under a
   label that names a matter) — is the organisation's account (where to pay it), except the person's:
   the profile's IBAN, any IBAN at a bank, and one labelled as theirs ("Ihre IBAN", "Kontoinhaber",
   "IBAN des Zahlungspflichtigen", "Kunden-IBAN").
3. *By its label*, matched as words after folding case and umlauts (a keyword of four letters or less
   must be the whole label, so "USt-IdNr." is never "IdNr"):

   - **the organisation's own**: USt-IdNr./VAT, a register (by its label; or in the value HRB, HRA or
     GnR with its number, and VR or PR with its number only beside a court or register word — "PR 12" is
     as often a ticket — never under a label that names a matter), Gläubiger-ID, BIC, a bank account
     number (at a bank it is the person's account), WEEE and Betriebsnummer, and a *Steuernummer* —
     which is the person's only on a letter from a tax office (every invoice prints the seller's);
   - **about you** (issued to the person, kept for years) — never when the label names someone else
     ("des Kindes", "Ehegatte", "partner", "spouse": a family member's number is theirs): Steuer-ID (a
     bare "Identifikationsnummer" or a label ending in "IdNr" — "St.-IdNr.", "Steuerliche IdNr." — only
     with eleven digits: other offices number people too), Rentenversicherungs-/SV-Nummer (by its
     label, or by its shape — 2 + 6 digits, a letter, 3 digits — under a label that mentions an
     insurance: "Versicherungs-Nr."), Krankenversichertennummer (by its label, "KV-Nummer", or by its
     shape — a letter and 9 digits — under an insurance label from a health insurer), Matrikelnummer,
     the Rundfunkbeitrag's Beitragsnummer (from the Beitragsservice or on a broadcasting-fee letter), a
     Steuernummer from a tax office, a car's number plate (Kfz-Kennzeichen), and identity documents:
     passport, residence permit and ID card (an "Ausweisnummer" only from an authority — at a library
     or gym it is a membership card);
   - **a case reference** (one matter): Aktenzeichen, Geschäftszeichen, Kassenzeichen, invoice, order,
     tracking (Sendungsnummer) and claim numbers, "Unser/Ihr Zeichen", Vorgang;
   - **yours with this organisation**: customer, contract, policy, member, employee, account, SEPA mandate
     and meter numbers.
4. *Anything else* is a number of yours with the organisation: a call sheet may show one number too many,
   but never hides one you need.

**Where it is shown.** *About you* lists the personal numbers once, with the latest letter that shows
them; *documents* the identity documents with their expiry (the letter's expiry to-do — only of an
identity-document or residence-permit letter, or one whose title names a passport, ID card or residence
title: a library card, student ID or Visa card that expires is none — flagged when that date is not
confirmed against the letter) and the renewal window the Ideas use
(:data:`~ordnung.secretary.triggers.IDENTITY_WINDOW_DAYS`, :data:`~ordnung.secretary.triggers.PERMIT_WINDOW_DAYS`;
a residence permit's note says what § 81 Abs. 4 AufenthG means before it expires and after). Each
organisation gets a *call sheet* — contact details, every number of yours its letters show, its open
cases, its own numbers apart, its last letter — when it has a number of yours that is not an identity
document's, or an open case. Its phone, e-mail and website are each the newest letter's without scam
signs that shows one (:func:`_contact`), else the organisation's record — unless a letter of it with scam
signs shows that value: reading a letter fills the record's empty fields before its scam checks run, so a
letter imitating a known sender could put its own phone number next to your customer numbers. A *case reference* is listed while its thread (else its letter) has an open
or snoozed one-off to-do (putting it off does not close the case) — the thread's own or one of its
letters' (a to-do added to a letter of the thread keeps it open): a recurring payment keeps a contract
going, not a case, so an old order number drops out. Its next step is the earliest (on the same day a
deadline or appointment before its fee or paperwork); a fee paid at the appointment
(:func:`~ordnung.secretary.triggers.paid_at_appointment`) counts on its day, never on a transfer day
(``at_appointment``). Within an organisation the same number (compared without spaces and marks) is one
entry; the latest letter's label wins.

**Check digits** (:func:`check_number`), where a public algorithm exists: the Steuer-ID (§ 139b AO; the
BZSt's specification: eleven digits, not starting with 0, in the first ten one digit twice — or three
times, never three in a row — and the ISO/IEC 7064 MOD 11,10 check digit), the Rentenversicherungsnummer
(§ 147 SGB VI, § 2 Abs. 6 VKVV: the letter as its place in the alphabet, weights 2 1 2 5 7 1 2 1 2 1 2 1,
cross sums, modulo 10), the Krankenversichertennummer (§ 290 SGB V, the GKV-Spitzenverband's guideline:
the letter as its place, weights 1 2 1 2 …, cross sums, modulo 10) and the IBAN (ISO 13616,
:mod:`ordnung.money.iban`). A passing check rules out almost every misread digit; it never proves the
number is the person's. A number of such a kind that fails says "does not check — compare with the
letter"; every other number has no check.

**Copying** puts a number as forms want it: a Steuer-ID, social or health insurance number or IBAN
without spaces, a number of digit groups separated by spaces as one run of digits, anything else as
printed.

Known limits, documented rather than patched: labels in languages other than German and English fall to
rule 4; a Steuernummer on a tax adviser's letter counts as the adviser's; a private health insurer's
member number of another shape has no check; the Steuernummer's own check digits (they differ per Land)
are not checked; the published Rentenversicherungsnummer check lets a 0/4 or 3/7 misread in its fifth
digit pass (weight 7 with one cross sum); a value the model split or joined differently on two letters
is two entries; a label that only says "Kontoinhaber" beside the organisation's own IBAN makes it the
person's (hidden on screen, never lost).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from ordnung.models import (
    CallSheet,
    Case,
    CaseItemRef,
    Document,
    DocumentExtraction,
    IdentityDocument,
    Item,
    LetterRef,
    MyNumber,
    MyNumbers,
    NumberCheck,
    NumberGroup,
    OpenCase,
    Party,
)
from ordnung.money.iban import grouped as iban_grouped
from ordnung.money.iban import inspect_iban
from ordnung.money.iban import normalize as iban_normalize
from ordnung.secretary.triggers import (
    IDENTITY_WINDOW_DAYS,
    PERMIT_WINDOW_DAYS,
    paid_at_appointment,
    unconfirmed_reason,
)

# --------------------------------------------------------------------------------------------------
# Kinds
# --------------------------------------------------------------------------------------------------

#: kind → (group, plain-English name). The group decides where a number is shown.
KINDS: dict[str, tuple[NumberGroup, str]] = {
    # about you
    "tax_id": ("about_you", "Tax ID (Steuer-ID)"),
    "tax_number": ("about_you", "Tax number (Steuernummer)"),
    "social_insurance": ("about_you", "Social insurance number (Rentenversicherungsnummer)"),
    "health_insurance": ("about_you", "Health insurance number (Krankenversichertennummer)"),
    "student": ("about_you", "Student number (Matrikelnummer)"),
    "broadcasting_fee": ("about_you", "Broadcasting fee number (Beitragsnummer)"),
    "vehicle": ("about_you", "Number plate (Kfz-Kennzeichen)"),
    # identity documents
    "passport": ("document", "Passport number"),
    "residence_permit": ("document", "Residence permit number"),
    "id_card": ("document", "ID card number"),
    # yours with one organisation
    "customer": ("organisation", "Customer number"),
    "contract": ("organisation", "Contract number"),
    "policy": ("organisation", "Policy number"),
    "member": ("organisation", "Member number"),
    "employee": ("organisation", "Employee number"),
    "account": ("organisation", "Account number"),
    "mandate": ("organisation", "Direct debit mandate (Mandatsreferenz)"),
    "meter": ("organisation", "Meter or supply point"),
    "other": ("organisation", "Your number"),
    # one matter
    "case_file": ("case", "Case reference (Aktenzeichen)"),
    "payment_reference": ("case", "Payment reference (Kassenzeichen)"),
    "invoice": ("case", "Invoice number"),
    "order": ("case", "Order number"),
    "tracking": ("case", "Tracking number (Sendungsnummer)"),
    "reference": ("case", "Reference"),
    # the organisation's own
    "vat_id": ("theirs", "VAT ID (USt-IdNr.)"),
    "register": ("theirs", "Company register"),
    "creditor_id": ("theirs", "Creditor ID (Gläubiger-ID)"),
    "iban": ("theirs", "Bank account (IBAN)"),
    "bic": ("theirs", "BIC"),
    "their_tax_number": ("theirs", "Their tax number"),
    "their_other": ("theirs", "Their number"),
}
IDENTITY_KINDS = frozenset({"passport", "residence_permit", "id_card"})
CHECKED_KINDS = frozenset({"tax_id", "social_insurance", "health_insurance", "iban"})
"""Kinds with a public check-digit algorithm (and a copy form without spaces)."""

TAX_OFFICE_DOC_KINDS = frozenset({"tax_assessment", "tax_letter"})
AUTHORITY_PARTY_KINDS = frozenset({"authority", "immigration_office", "tax_office"})
RESIDENCE_EXTENSION_NOTE = (
    "Apply before it expires: your permit then counts as still valid until the office decides "
    "(§ 81 Abs. 4 S. 1–2 AufenthG; not for a Schengen visa) — ask for a Fiktionsbescheinigung."
)
RESIDENCE_EXPIRED_NOTE = (
    "If you applied before it expired, it counts as valid until the office decides (§ 81 Abs. 4 S. 1 "
    "AufenthG) — keep your Fiktionsbescheinigung. If not, contact the Ausländerbehörde now: after a late "
    "application the office may keep it in force only to avoid undue hardship (§ 81 Abs. 4 S. 3 AufenthG)."
)
IDENTITY_NOTE = (
    "Renewing a passport can take months, and a residence permit usually runs only as long as the passport."
)


# --------------------------------------------------------------------------------------------------
# Normalising
# --------------------------------------------------------------------------------------------------

_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_SMALL_WORD = re.compile(r"(?<![^\W\d_])[a-zäöüß]{2,}(?![^\W\d_])")
_DIGIT_GROUPS = re.compile(r"\d+(?: \d+)+")


def label_key(label: str) -> str:
    """``"Kunden-Nr."`` → ``"kundennr"``: case and umlauts folded, only letters and digits kept."""
    folded = unicodedata.normalize("NFKC", label).casefold().translate(_TRANSLIT)
    return "".join(char for char in folded if char.isalnum())


def compact(value: str) -> str:
    """``"57 216 480 393"`` → ``"57216480393"``: upper case, only letters and digits (for comparing)."""
    return "".join(char for char in unicodedata.normalize("NFKC", value).upper() if char.isalnum())


def printed(value: str) -> str:
    """The value as printed, with runs of white space made one space."""
    return " ".join(value.split())


def is_number(value: str) -> bool:
    """Rule 1: a number has a digit and no word in small letters ("2. OG links" is a description)."""
    text = printed(value)
    return any(char.isdigit() for char in text) and _SMALL_WORD.search(text) is None


# --------------------------------------------------------------------------------------------------
# Check digits
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DigitCheck:
    """The outcome of a check-digit test: ``ok``, ``fails`` or ``none`` (no public algorithm), and why."""

    status: NumberCheck
    note: str | None = None


NO_CHECK = DigitCheck("none")
_COMPARE = "compare it with the letter"
_NOT_PROOF = "A misread digit would almost always fail it; it doesn't prove the number is yours."


def _cross_sum(value: int) -> int:
    return sum(int(digit) for digit in str(value))


def tax_id_problem(value: str) -> str | None:
    """Why ``value`` is no valid Steuer-ID (§ 139b AO; the digit rules are the BZSt's specification),
    or ``None`` when it passes every rule."""
    digits = compact(value)
    if not digits.isdigit() or len(digits) != 11:
        return f"A Steuer-ID has 11 digits; this has {sum(char.isdigit() for char in digits)}"
    if digits[0] == "0":
        return "A Steuer-ID never starts with 0"
    first = digits[:10]
    counts = sorted((first.count(digit) for digit in set(first)), reverse=True)
    triple = counts[0] == 3 and counts[1:] == [1] * 7
    if not (counts[0] == 2 and counts[1:] == [1] * 8) and not triple:
        return "In a Steuer-ID's first ten digits exactly one digit appears twice or three times"
    if triple and re.search(r"(\d)\1\1", first):
        return "A digit that appears three times in a Steuer-ID never stands three in a row"
    product = 10
    for digit in first:
        total = (int(digit) + product) % 10 or 10
        product = (total * 2) % 11
    check = (11 - product) % 10
    if check != int(digits[10]):
        return "The last digit is not the Steuer-ID's check digit"
    return None


_RVNR = re.compile(r"^(\d{2})(\d{6})([A-Z])(\d{2})(\d)$")
_RVNR_WEIGHTS = (2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1)


def is_social_insurance_shape(value: str) -> bool:
    """Two digits, six digits (the birth date), a letter, two digits and the check digit."""
    return _RVNR.match(compact(value)) is not None


def social_insurance_problem(value: str) -> str | None:
    """Why ``value`` is no valid Rentenversicherungsnummer (§ 147 SGB VI; check digit: § 2 Abs. 6 VKVV),
    or ``None``."""
    match = _RVNR.match(compact(value))
    if match is None:
        return "A Rentenversicherungsnummer has 12 characters: 8 digits, a letter and 3 digits"
    area, birth, letter, serial, check = match.groups()
    digits = f"{area}{birth}{ord(letter) - ord('A') + 1:02d}{serial}"
    total = sum(_cross_sum(int(digit) * weight) for digit, weight in zip(digits, _RVNR_WEIGHTS, strict=True))
    return None if total % 10 == int(check) else "The last digit is not the check digit"


_KVNR = re.compile(r"^([A-Z])(\d{8})(\d)$")


def is_health_insurance_shape(value: str) -> bool:
    """A letter, eight digits and the check digit (the statutory health insurance's number)."""
    return _KVNR.match(compact(value)) is not None


def health_insurance_problem(value: str) -> str | None:
    """Why ``value`` is no valid Krankenversichertennummer (§ 290 SGB V; its check digit is the
    GKV-Spitzenverband's guideline), or ``None``."""
    match = _KVNR.match(compact(value))
    if match is None:
        return "A Krankenversichertennummer has a letter and nine digits"
    letter, body, check = match.groups()
    digits = f"{ord(letter) - ord('A') + 1:02d}{body}"
    total = sum(_cross_sum(int(digit) * (1 if index % 2 == 0 else 2)) for index, digit in enumerate(digits))
    return None if total % 10 == int(check) else "The last digit is not the check digit"


def _check(problem: str | None, what: str, law: str) -> DigitCheck:
    if problem is None:
        return DigitCheck("ok", f"Passes the {what} check ({law}). {_NOT_PROOF}")
    return DigitCheck(
        "fails", f"Does not pass the {what} check ({law}): {problem[0].lower()}{problem[1:]} — {_COMPARE}."
    )


def check_number(kind: str, value: str) -> DigitCheck:
    """The check-digit test for a number of ``kind`` (``none`` for kinds without a public algorithm)."""
    if kind == "tax_id":
        return _check(tax_id_problem(value), "Steuer-ID", "§ 139b AO, the BZSt's specification")
    if kind == "social_insurance":
        return _check(social_insurance_problem(value), "Rentenversicherungsnummer", "§ 147 SGB VI, § 2 VKVV")
    if kind == "health_insurance":
        if not is_health_insurance_shape(value):
            return NO_CHECK  # a private insurer's member number has its own shape
        return _check(
            health_insurance_problem(value),
            "Krankenversichertennummer",
            "§ 290 SGB V, the GKV-Spitzenverband's guideline",
        )
    if kind == "iban" or (kind == "account" and inspect_iban(value).shape_ok):
        found = inspect_iban(value)
        if found.valid:
            return DigitCheck(
                "ok", "The IBAN's check digits are valid — that only rules out typos, not fraud."
            )
        return DigitCheck("fails", f"Does not check: {' '.join(found.problems)} Compare it with the letter.")
    return NO_CHECK


# --------------------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------------------


_IBAN_WORDS = ("iban", "kontonummer", "kontonr", "kto", "ktonr", "bankverbindung", "bankaccount")


@dataclass(frozen=True)
class Context:
    """Where a number was printed: the sender's kind, the letter's kind, and the person's own IBAN."""

    party_kind: str | None = None
    doc_kind: str | None = None
    own_iban: str | None = None


def _has(key: str, words: Iterable[str]) -> bool:
    """Whether a label key holds one of ``words`` (a word of four letters or less must be all of it)."""
    return any(key == word if len(word) <= 4 else word in key for word in words)


def _label_words(label: str) -> list[str]:
    """``"IBAN des Zahlungspflichtigen"`` → ``["iban", "des", "zahlungspflichtigen"]`` (folded)."""
    folded = unicodedata.normalize("NFKC", label).casefold().translate(_TRANSLIT)
    return re.findall(r"[^\W_]+", folded)


def _word_starts(label: str, stems: Iterable[str]) -> bool:
    """Whether a word of the label starts with one of ``stems``."""
    stems = tuple(stems)
    return any(word.startswith(stems) for word in _label_words(label))


_CREDITOR_ID = re.compile(r"^DE\d{2}ZZZ\d{11}$")
_VAT_ID = re.compile(r"^DE\d{9}$")
_REGISTER_IN_VALUE = re.compile(r"\b(?:HRB|HRA|GnR)\s*\d+")
_ASSOCIATION_IN_VALUE = re.compile(r"\b(?:VR|PR)\s+\d+\b")
_REGISTER_WORDS = ("register", "amtsgericht", "registergericht")

_THEIRS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("vat_id", ("ustid", "umsatzsteuer", "vatid", "vatno", "vatnumber", "vat", "uid", "ustidnr")),
    (
        "register",
        (
            "register",
            "amtsgericht",
            "handelsregister",
            "hrb",
            "hra",
            "gnr",
            "vr",
            "registergericht",
            "weeereg",
        ),
    ),
    ("creditor_id", ("glaeubiger", "creditor", "ci", "credid")),
    ("bic", ("bic", "swift")),
    ("iban", _IBAN_WORDS),
    ("their_other", ("betriebsnummer", "versicherungsteuer")),
)
_TAX_NUMBER = ("steuernummer", "steuernr", "stnr", "taxnumber", "taxno")
_ABOUT_YOU: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tax_id", ("steuerid", "steueridentifikationsnummer", "taxid", "tin")),
    (
        "social_insurance",
        (
            "rentenversicherungsnummer",
            "rentenversicherungsnr",
            "rvnr",
            "rvnummer",
            "svnr",
            "svnummer",
            "sozialversicherungsnummer",
            "sozialversicherungsnr",
            "sozialversicherung",
            "socialsecurity",
            "socialinsurance",
            "pensioninsurance",
        ),
    ),
    (
        "health_insurance",
        (
            "krankenversichertennummer",
            "krankenversicherungsnummer",
            "kvnr",
            "kvnummer",
            "versichertennummer",
            "versichertennr",
            "healthinsurancenumber",
        ),
    ),
    ("student", ("matrikel", "matrnr", "studentnumber", "studentid", "studierendennummer")),
    ("passport", ("passport", "reisepass", "passnummer", "passnr", "pass")),
    (
        "residence_permit",
        ("aufenthaltstitel", "aufenthaltserlaubnis", "residencepermit", "eatnummer", "eatnr"),
    ),
    (
        "vehicle",
        (
            "kfzkennzeichen",
            "fahrzeugkennzeichen",
            "amtlicheskennzeichen",
            "amtlkennzeichen",
            "numberplate",
            "licenseplate",
            "licenceplate",
            "registrationplate",
        ),
    ),
)
_TAX_ID_BY_SHAPE = ("identifikationsnummer", "idnr")
"""Labels that are a Steuer-ID only with its eleven digits (other offices number people too)."""
_ID_CARD = ("personalausweis", "idcard", "identitycard")
_ID_CARD_AT_AUTHORITY = ("ausweisnummer", "ausweisnr", "ausweis")
_BROADCASTING = ("beitragsnummer", "beitragsnr", "rundfunk")
_SOCIAL_INSURANCE_BY_SHAPE = ("vers", "rv", "sv", "sozial", "renten", "pension", "insurance")
"""Label parts that make a number of the Rentenversicherungsnummer's shape one (``Versicherungs-Nr.``)."""
_HEALTH_INSURANCE_BY_SHAPE = ("vers", "kv", "kranken", "health")
"""Label parts that make a number of the Krankenversichertennummer's shape one, at a health insurer."""
_OTHER_PERSON = (
    "kind",
    "child",
    "sohn",
    "tochter",
    "daughter",
    "ehegatt",
    "ehepartner",
    "ehefrau",
    "ehemann",
    "lebenspartner",
    "partner",
    "spouse",
    "husband",
    "wife",
)
"""Label words that name someone else ("Identifikationsnummer des Kindes"): never *about you*."""
_YOUR_ACCOUNT = (
    "ihr",
    "your",
    "kontoinhab",
    "zahlungspflicht",
    "zahler",
    "payer",
    "debtor",
    "debitor",
    "mandatsgeber",
    "kunde",
    "customer",
)
"""Label words that make an IBAN the person's own ("Ihre IBAN", "IBAN des Zahlungspflichtigen")."""
_CASE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("payment_reference", ("kassenzeichen", "buchungszeichen")),
    (
        "case_file",
        (
            "aktenzeichen",
            "az",
            "geschaeftszeichen",
            "gz",
            "geschaeftsnummer",
            "fallnummer",
            "casenumber",
            "filenumber",
        ),
    ),
    ("invoice", ("rechnung", "invoice", "rgnr", "belegnr", "belegnummer", "mahnnummer")),
    ("tracking", ("sendungsnummer", "sendungsnr", "paketnummer", "tracking", "trackingnummer")),
    ("order", ("bestell", "auftrag", "order")),
)
_MANDATE = ("mandat",)
_REFERENCE = (
    "vorgang",
    "zeichen",
    "referenz",
    "reference",
    "ticket",
    "schaden",
    "claim",
    "bescheid",
    "mediennummer",
    "anfrage",
)
_YOURS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("customer", ("kunden", "customer", "kdnr", "kd", "mieter", "tenant")),
    (
        "contract",
        (
            "vertragsnummer",
            "vertragsnr",
            "vertrag",
            "contract",
            "abonummer",
            "abonnement",
            "subscription",
            "abo",
        ),
    ),
    (
        "policy",
        ("police", "policy", "versicherungsschein", "versicherungsnummer", "versnr", "vsnr", "versicherung"),
    ),
    ("employee", ("personalnummer", "persnr", "personalnr", "employee", "mitarbeiter")),
    ("member", ("mitglied", "member", "benutzer", "leser", "ausweis", "karte", "card")),
    ("meter", ("zaehler", "meter", "marktlokation", "messlokation", "malo", "melo")),
    ("account", ("konto", "account", "user")),
)


def _first(key: str, table: Sequence[tuple[str, tuple[str, ...]]]) -> str | None:
    return next((kind for kind, words in table if _has(key, words)), None)


def _names_a_matter(key: str) -> bool:
    """A label that says what the number is — a case, or yours with the organisation (not an account):
    it wins over a value's look (a "Kundennummer" of the VAT ID's shape, "Bestellnummer PR 2024")."""
    return (
        _has(key, _MANDATE)
        or _has(key, _REFERENCE)
        or _first(key, _CASE) is not None
        or _first(key, [row for row in _YOURS if row[0] != "account"]) is not None
    )


def _is_register(key: str, value: str) -> bool:
    """A register entry in the value: HRB, HRA or GnR with its number; VR (Vereinsregister) or PR
    (Partnerschaftsregister) only beside a court or register word — "PR 12" is as often a ticket."""
    if _REGISTER_IN_VALUE.search(value):
        return True
    return _ASSOCIATION_IN_VALUE.search(value) is not None and (
        _has(key, _REGISTER_WORDS) or _has(label_key(value), _REGISTER_WORDS)
    )


def _is_iban(key: str, flat: str) -> bool:
    """A valid IBAN; or one that fails only its check digits (its country's length) or stands under an
    IBAN label — a misread IBAN, which :func:`check_number` then reports."""
    found = inspect_iban(flat)
    if found.valid:
        return True
    return found.shape_ok and (
        (found.country is not None and found.length_ok is True) or _has(key, ("iban",))
    )


def _iban_kind(label: str, value: str, ctx: Context) -> str:
    """An IBAN: the person's account — their own, at a bank, or labelled as theirs ("Ihre IBAN") —
    else the organisation's, where to pay it."""
    own = ctx.own_iban and iban_normalize(ctx.own_iban) == iban_normalize(value)
    theirs_by_label = _word_starts(label, _YOUR_ACCOUNT)
    return "account" if own or ctx.party_kind == "bank" or theirs_by_label else "iban"


def classify(label: str, value: str, ctx: Context | None = None) -> str | None:
    """The kind of a printed number (``KINDS``), or ``None`` when it is no number (module policy)."""
    ctx = ctx or Context()
    if not is_number(value):
        return None
    key, flat = label_key(label), compact(value)
    matter = _names_a_matter(key)
    # 2. by shape
    if _CREDITOR_ID.match(flat):
        return "creditor_id"
    if _VAT_ID.match(flat) and not matter:
        return "vat_id"
    if _is_iban(key, flat) and not (matter and not inspect_iban(flat).valid):
        return _iban_kind(label, value, ctx)
    # 3. by label: the organisation's own first (a register is never a number of yours)
    if not matter and _is_register(key, value):
        return "register"
    if _has(key, _TAX_NUMBER):
        from_tax_office = ctx.party_kind == "tax_office" or ctx.doc_kind in TAX_OFFICE_DOC_KINDS
        return "tax_number" if from_tax_office else "their_tax_number"
    theirs = _first(key, _THEIRS)
    if theirs == "iban":
        return "account" if ctx.party_kind == "bank" else "their_other"  # an account number, not an IBAN
    if theirs is not None:
        return theirs
    return _personal(label, key, value, ctx) or _case_or_yours(key)


def _personal(label: str, key: str, value: str, ctx: Context) -> str | None:
    if _word_starts(label, _OTHER_PERSON):
        return None  # a child's or spouse's number is not about you
    kind = _first(key, _ABOUT_YOU)
    if kind is not None:
        return kind
    if key.startswith("kennzeichen"):
        return "vehicle"
    flat = compact(value)
    tax_id_label = _has(key, _TAX_ID_BY_SHAPE) or (key.endswith("idnr") and not _has(key, ("ustidnr",)))
    if tax_id_label and flat.isdigit() and len(flat) == 11:
        return "tax_id"
    if is_social_insurance_shape(value) and any(part in key for part in _SOCIAL_INSURANCE_BY_SHAPE):
        return "social_insurance"
    if (
        ctx.party_kind == "health_insurer"
        and is_health_insurance_shape(value)
        and any(part in key for part in _HEALTH_INSURANCE_BY_SHAPE)
    ):
        return "health_insurance"
    if _has(key, _BROADCASTING) and (
        "rundfunk" in key or ctx.party_kind == "public_broadcaster" or ctx.doc_kind == "broadcasting_fee"
    ):
        return "broadcasting_fee"
    if _has(key, _ID_CARD):
        return "id_card"
    at_authority = ctx.party_kind in AUTHORITY_PARTY_KINDS or ctx.doc_kind == "identity_document"
    if at_authority and _has(key, _ID_CARD_AT_AUTHORITY):
        return "id_card"
    if ctx.doc_kind == "residence_permit" and _has(key, ("dokumentennummer", "kartennummer", "seriennummer")):
        return "residence_permit"
    return None


def _case_or_yours(key: str) -> str:
    if _has(key, _MANDATE):
        return "mandate"  # a Mandatsreferenz is no case reference
    kind = _first(key, _CASE)
    if kind is not None:
        return kind
    if _has(key, _REFERENCE):
        return "reference"
    return _first(key, _YOURS) or "other"


def display_value(kind: str, value: str) -> str:
    """The value grouped for reading (a Steuer-ID ``57 216 480 393``, an IBAN in fours)."""
    flat = compact(value)
    if kind == "tax_id" and len(flat) == 11:
        return f"{flat[:2]} {flat[2:5]} {flat[5:8]} {flat[8:]}"
    if kind == "social_insurance" and is_social_insurance_shape(flat):
        return f"{flat[:2]} {flat[2:8]} {flat[8]} {flat[9:]}"
    if kind in ("iban", "account") and inspect_iban(flat).shape_ok:
        return iban_grouped(iban_normalize(value))
    return printed(value)


def copy_value(kind: str, value: str) -> str:
    """What "Copy" puts on the clipboard: checked kinds and digit groups without spaces, else as printed."""
    text = printed(value)
    if kind in CHECKED_KINDS or (kind == "account" and inspect_iban(text).shape_ok):
        return compact(text)
    if _DIGIT_GROUPS.fullmatch(text):
        return text.replace(" ", "")
    return text


# --------------------------------------------------------------------------------------------------
# Building the page
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sighting:
    """One number as one letter shows it."""

    label: str
    value: str
    doc: Document
    party: Party | None
    kind: str | None = None  # decided by where it stands, not by its label (a payment IBAN)


@dataclass
class NumbersInput:
    """A snapshot of the ledger, read by the caller (:func:`ordnung.views.my_numbers`).

    ``documents`` are live letters; ``items`` their to-dos (and those of no letter); ``open_items`` the
    to-dos worth acting on — open or snoozed (putting a to-do off keeps its case open), no scam signs,
    not taken over by a reminder; ``expiry_classes`` says for each expiry to-do whether it is a
    ``permit``, an ``identity`` document or ``other`` (:func:`ordnung.secretary.triggers.expiry_class`).
    """

    today: date
    documents: Sequence[Document]
    parties: Mapping[str, Party]
    cases: Mapping[str, Case]
    items: Sequence[Item]
    open_items: Sequence[Item]
    extractions: Mapping[str, DocumentExtraction | None] = field(default_factory=dict)
    suspicious: frozenset[str] = frozenset()
    expiry_classes: Mapping[str, str] = field(default_factory=dict)
    own_iban: str | None = None


def _day_of(doc: Document) -> str:
    return doc.doc_date or doc.received_date or doc.created_at[:10]


def _newest_first(documents: Iterable[Document]) -> list[Document]:
    return sorted(documents, key=lambda doc: (_day_of(doc), doc.created_at, doc.id), reverse=True)


def _sightings(data: NumbersInput) -> list[Sighting]:
    """Every number of every live letter without scam signs, newest letter first."""
    found: list[Sighting] = []
    for doc in _newest_first(data.documents):
        if doc.id in data.suspicious:
            continue
        party = data.parties.get(doc.party_id) if doc.party_id else None
        extraction = data.extractions.get(doc.id)
        sender = extraction.sender.identifiers if extraction and extraction.sender else []
        for identifier in (*doc.references, *sender):
            found.append(Sighting(identifier.label, identifier.value, doc, party))
        if doc.payment and doc.payment.iban:
            # where to pay the sender — the payee's name in the label never makes it a number of yours
            payee = printed(doc.payment.payee or "")
            label = f"IBAN for payments to {payee}" if payee else "IBAN for payments"
            own = bool(data.own_iban) and compact(doc.payment.iban) == compact(data.own_iban or "")
            found.append(Sighting(label, doc.payment.iban, doc, party, "account" if own else "iban"))
    return found


def _key(*parts: str) -> str:
    return "num_" + hashlib.sha1("|".join(parts).encode(), usedforsecurity=False).hexdigest()[:12]


def _letter_ref(doc: Document) -> LetterRef:
    return LetterRef(id=doc.id, title=doc.title or doc.filename, date=_day_of(doc), kind=doc.kind)


@dataclass
class _Entry:
    kind: str
    sighting: Sighting
    letters: set[str] = field(default_factory=set)
    cases: set[str] = field(default_factory=set)

    def model(self) -> MyNumber:
        group, name = KINDS[self.kind]
        s = self.sighting
        check = check_number(self.kind, s.value)
        return MyNumber.model_validate(
            {
                "key": _key(self.kind, s.party.id if s.party else "", compact(s.value)),
                "kind": self.kind,
                "group": group,
                "name": name,
                "label": printed(s.label) or name,
                "value": printed(s.value),
                "display": display_value(self.kind, s.value),
                "copy_value": copy_value(self.kind, s.value),
                "check": check.status,
                "check_note": check.note,
                "party_id": s.party.id if s.party else None,
                "party_name": s.party.name if s.party else None,
                "letter": _letter_ref(s.doc),
                "letters": len(self.letters),
            }
        )


def _collect(data: NumbersInput) -> tuple[dict[tuple[str, str], _Entry], dict[tuple[str, str], _Entry]]:
    """Entries per (party, number) — the call sheets' — and per (kind, number) for About you."""
    by_party: dict[tuple[str, str], _Entry] = {}
    personal: dict[tuple[str, str], _Entry] = {}
    for s in _sightings(data):
        ctx = Context(s.party.kind if s.party else None, s.doc.kind, data.own_iban)
        kind = (s.kind if is_number(s.value) else None) if s.kind else classify(s.label, s.value, ctx)
        flat = compact(s.value)
        if kind is None or (kind == "account" and data.own_iban and flat == compact(data.own_iban)):
            continue  # the person's own IBAN is in their profile
        entry = by_party.setdefault((s.party.id if s.party else "", flat), _Entry(kind, s))
        entry.letters.add(s.doc.id)
        if s.doc.case_id:
            entry.cases.add(s.doc.case_id)
        if KINDS[kind][0] in ("about_you", "document"):
            mine = personal.setdefault((kind, flat), _Entry(kind, s))
            mine.letters.add(s.doc.id)
    return by_party, personal


def _first_day(due: str | None, send_by: str | None) -> str:
    """The day to act: the send-by day when it comes first, else the due date (undated last)."""
    if send_by and (not due or send_by <= due):
        return send_by
    return due or "9999-12-31"


_KIND_RANK = {"deadline": 0, "appointment": 1, "payment": 2, "task": 3}
"""On the same day the deadline or appointment is the case's next step, before its fee or paperwork."""


def _one_off(item: Item) -> bool:
    return item.recurrence is None and item.kind not in ("expiry", "milestone")


def _next_item(data: NumbersInput, item: Item) -> CaseItemRef:
    """A case's next to-do as the record gives it: a fee paid at the appointment has no transfer day."""
    in_person = paid_at_appointment(item, data.items)
    return CaseItemRef(
        id=item.id,
        title=item.title,
        kind=item.kind,
        due_date=item.due_date,
        send_by=None if in_person else item.send_by,
        at_appointment=in_person,
        needs_check=unconfirmed_reason(item) is not None,
    )


def _open_cases(data: NumbersInput, entries: Iterable[_Entry]) -> list[OpenCase]:
    """Case references grouped by thread (else letter), while it has an open one-off to-do — of the
    thread (its own, or of one of its letters), else of the letter."""
    groups: dict[str, list[_Entry]] = {}
    for entry in entries:
        if KINDS[entry.kind][0] != "case":
            continue
        for thread in sorted(entry.cases) or sorted(f"doc:{doc}" for doc in entry.letters):
            groups.setdefault(thread, []).append(entry)
    cases: list[OpenCase] = []
    documents = {doc.id: doc for doc in data.documents}
    thread_letters: dict[str, set[str]] = {}
    for doc in data.documents:
        if doc.case_id:
            thread_letters.setdefault(doc.case_id, set()).add(doc.id)
    for thread, refs in groups.items():
        by_doc = thread.startswith("doc:")
        wanted = thread.removeprefix("doc:")
        letters_of = {wanted} if by_doc else thread_letters.get(wanted, set())
        found = [
            _next_item(data, item)
            for item in data.open_items
            if _one_off(item)
            and ((not by_doc and item.case_id == wanted) or (item.doc_id or "") in letters_of)
        ]
        if not found:
            continue
        nxt = min(
            found,
            key=lambda ref: (_first_day(ref.due_date, ref.send_by), _KIND_RANK.get(ref.kind, 9), ref.id),
        )
        case = None if by_doc else data.cases.get(wanted)
        letters = _newest_first(
            documents[doc_id] for entry in refs for doc_id in entry.letters if doc_id in documents
        )
        party = refs[0].sighting.party
        cases.append(
            OpenCase.model_validate(
                {
                    "key": _key("case", thread),
                    "case_id": None if by_doc else wanted,
                    "title": (case.title if case else None) or letters[0].title or letters[0].filename,
                    "party_id": party.id if party else None,
                    "party_name": party.name if party else None,
                    "references": [entry.model() for entry in refs],
                    "next_item": nxt,
                    "open_items": len(found),
                    "letter": _letter_ref(letters[0]),
                }
            )
        )
    return sorted(cases, key=lambda c: (_action_day_of(c), c.title.casefold(), c.key))


def _action_day_of(case: OpenCase) -> str:
    nxt = case.next_item
    return _first_day(nxt.due_date, nxt.send_by) if nxt else "9999-12-31"


def _document_status(kind: str, valid_until: date | None, today: date) -> str:
    if valid_until is None:
        return "unknown"
    days = (valid_until - today).days
    if days < 0:
        return "expired"
    window = PERMIT_WINDOW_DAYS if kind == "residence_permit" else IDENTITY_WINDOW_DAYS
    return "renew_soon" if days <= window else "ok"


_DOCUMENT_NAMES = {
    "passport": "Passport",
    "residence_permit": "Residence permit",
    "id_card": "ID card",
    "identity_document": "Identity document",
}


_IDENTITY_TITLE = ("passport", "reisepass", "personalausweis", "identity card", "national id")
_PERMIT_TITLE = (
    "aufenthalt",
    "residence permit",
    "residence title",
    "fiktionsbescheinigung",
    "blue card",
    "blaue karte",
    "visum",
)
_VISA = re.compile(r"\bvisa\b(?!\s*(?:card|karte|debit|credit))", re.I)


def is_identity_expiry(item: Item, klass: str, doc: Document | None) -> bool:
    """An expiry of an identity document or residence title: from such a letter, or with a title that
    names one — not a library card, student ID ("Studierendenausweis") or Visa card that expires."""
    if doc is not None and doc.kind in ("identity_document", "residence_permit"):
        return True
    title = item.title.casefold()
    if klass == "identity":
        return any(word in title for word in _IDENTITY_TITLE)
    return klass == "permit" and (
        any(word in title for word in _PERMIT_TITLE) or _VISA.search(item.title) is not None
    )


def _identity_kind(item: Item, klass: str, numbers: Sequence[MyNumber]) -> str:
    if klass == "permit":
        return "residence_permit"
    title = item.title.casefold()
    if "personalausweis" in title or "id card" in title or "identity card" in title:
        return "id_card"
    if any(number.kind == "passport" for number in numbers) or "pass" in title:
        return "passport"
    return "identity_document"


def _identity_documents(
    data: NumbersInput, personal: Mapping[tuple[str, str], _Entry]
) -> list[IdentityDocument]:
    """One entry per identity-document expiry to-do, with the number its letter shows; numbers of an
    identity document without an expiry to-do get an entry of their own (valid until unknown)."""
    numbers = [entry.model() for entry in personal.values() if entry.kind in IDENTITY_KINDS]
    documents = {doc.id: doc for doc in data.documents}
    used: set[str] = set()
    found: list[IdentityDocument] = []
    expiries = [
        item
        for item in data.items
        if item.kind == "expiry"
        and item.status not in ("dismissed", "done")
        and data.expiry_classes.get(item.id) in ("permit", "identity")
        and item.doc_id not in data.suspicious
        and (item.doc_id is None or item.doc_id in documents)
        and is_identity_expiry(item, data.expiry_classes[item.id], documents.get(item.doc_id or ""))
    ]
    for item in sorted(expiries, key=lambda i: (i.due_date or "9999", i.id)):
        klass = data.expiry_classes[item.id]
        mine = [number for number in numbers if number.letter and number.letter.id == item.doc_id]
        kind = _identity_kind(item, klass, mine)
        number = next((n for n in mine if n.kind == kind), None) or (
            next((n for n in numbers if n.kind == kind and n.key not in used), None)
            if sum(n.kind == kind for n in numbers) == 1
            else None
        )
        if number is not None:
            used.add(number.key)
        found.append(_identity_document(data, kind, number, item, documents.get(item.doc_id or "")))
    for number in numbers:
        if number.key not in used:
            found.append(_identity_document(data, number.kind, number, None, None))
    return found


def _identity_document(
    data: NumbersInput, kind: str, number: MyNumber | None, item: Item | None, doc: Document | None
) -> IdentityDocument:
    until = date.fromisoformat(item.due_date) if item and item.due_date else None
    status = _document_status(kind, until, data.today)
    note = None
    if kind == "residence_permit":
        note = RESIDENCE_EXPIRED_NOTE if status == "expired" else RESIDENCE_EXTENSION_NOTE
    if kind == "passport" and status in ("renew_soon", "expired"):
        note = IDENTITY_NOTE
    letter = doc or next(
        (d for d in data.documents if number and number.letter and d.id == number.letter.id), None
    )
    return IdentityDocument.model_validate(
        {
            "key": _key("document", kind, item.id if item else (number.key if number else "")),
            "kind": kind,
            "name": _DOCUMENT_NAMES[kind],
            "number": number,
            "valid_until": until.isoformat() if until else None,
            "status": status,
            "note": note,
            "item_id": item.id if item else None,
            "needs_check": item is not None and unconfirmed_reason(item) is not None,
            "letter": _letter_ref(letter) if letter else None,
        }
    )


_CONTACT_FIELDS = ("phone", "email", "website")


def _contact_key(name: str, value: str) -> str:
    """A phone number by its digits, an e-mail address or a website without case and spaces."""
    return re.sub(r"\D", "", value) if name == "phone" else re.sub(r"\s", "", value).casefold()


def _contact(data: NumbersInput, party: Party, letters: Sequence[Document]) -> dict[str, str | None]:
    """A call sheet's phone, e-mail and website (module policy): each from the newest of ``letters``
    (the organisation's, without scam signs, newest first) whose sender shows one, else the record's —
    never a value one of its letters with scam signs shows."""
    scam_values: dict[str, set[str]] = {name: set() for name in _CONTACT_FIELDS}
    for doc in data.documents:
        extraction = data.extractions.get(doc.id)
        if doc.party_id == party.id and doc.id in data.suspicious and extraction and extraction.sender:
            for name in _CONTACT_FIELDS:
                if value := getattr(extraction.sender, name):
                    scam_values[name].add(_contact_key(name, value))
    found: dict[str, str | None] = {}
    for name in _CONTACT_FIELDS:
        shown = next(
            (
                value
                for doc in letters
                if (extraction := data.extractions.get(doc.id)) is not None
                and extraction.sender is not None
                and (value := getattr(extraction.sender, name))
            ),
            None,
        )
        record: str | None = getattr(party, name)
        if shown is None and record and _contact_key(name, record) not in scam_values[name]:
            shown = record
        found[name] = shown
    return found


def _call_sheets(
    data: NumbersInput, by_party: Mapping[tuple[str, str], _Entry], open_cases: Sequence[OpenCase]
) -> list[CallSheet]:
    sheets: list[CallSheet] = []
    letters_by_party: dict[str, list[Document]] = {}
    for doc in data.documents:
        if doc.party_id and doc.id not in data.suspicious:
            letters_by_party.setdefault(doc.party_id, []).append(doc)
    for party_id, party in data.parties.items():
        entries = [entry for (owner, _), entry in by_party.items() if owner == party_id]
        yours = [e for e in entries if KINDS[e.kind][0] in ("about_you", "organisation", "document")]
        cases = [case for case in open_cases if case.party_id == party_id]
        if not cases and not any(e.kind not in IDENTITY_KINDS for e in yours):
            continue
        letters = _newest_first(letters_by_party.get(party_id, []))
        order = {kind: index for index, kind in enumerate(KINDS)}
        sheets.append(
            CallSheet.model_validate(
                {
                    "party_id": party.id,
                    "name": party.name,
                    "kind": party.kind,
                    **_contact(data, party, letters),
                    "numbers": [
                        e.model() for e in sorted(yours, key=lambda e: (order[e.kind], e.sighting.label))
                    ],
                    "their_numbers": [
                        e.model()
                        for e in sorted(entries, key=lambda e: (order[e.kind], e.sighting.label))
                        if KINDS[e.kind][0] == "theirs"
                    ],
                    "open_cases": cases,
                    "last_letter": _letter_ref(letters[0]) if letters else None,
                    "open_items": sum(1 for item in data.open_items if item.party_id == party_id),
                }
            )
        )
    return sorted(sheets, key=lambda sheet: (sheet.name.casefold(), sheet.party_id))


def build_my_numbers(data: NumbersInput) -> MyNumbers:
    """The *My numbers* page: About you, identity documents, call sheets and open cases (module policy)."""
    by_party, personal = _collect(data)
    order = {kind: index for index, kind in enumerate(KINDS)}
    about = sorted(
        (entry for entry in personal.values() if KINDS[entry.kind][0] == "about_you"),
        key=lambda entry: (order[entry.kind], compact(entry.sighting.value)),
    )
    open_cases = _open_cases(data, by_party.values())
    return MyNumbers(
        today=data.today.isoformat(),
        about_you=[entry.model() for entry in about],
        documents=_identity_documents(data, personal),
        organisations=_call_sheets(data, by_party, open_cases),
        open_cases=open_cases,
    )
