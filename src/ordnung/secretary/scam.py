"""Payment-scam checks done by code, never by the model (SPEC § 21 "Scam checks").

* :func:`iban_valid` — ISO 13616 checksum (mod 97) plus the length of well-known countries.
* :func:`payment_mismatch` — a payment demand whose IBAN (or payee) differs from what was seen
  before for the same sender, or — for a sender with no payment history — from an organisation with
  a look-alike name (``Rundfunk-Beitragsservice – Zahlungszentrale`` vs ``Beitragsservice
  Musterstadt``). The ingestion pipeline adds the finding's message to the document's warnings; the
  triggers module turns it into a ``scam`` Idea. No warning does not mean a payment is safe.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz, utils

from ordnung.db.store import Store
from ordnung.models import Party, PaymentDetails

FindingKind = Literal["invalid_iban", "iban_changed", "similar_party_iban", "payee_changed"]

#: IBAN lengths of countries a person in Germany commonly pays to (others: checksum only).
IBAN_LENGTHS: dict[str, int] = {
    "AT": 20,
    "BE": 16,
    "CH": 21,
    "CZ": 24,
    "DE": 22,
    "DK": 18,
    "ES": 24,
    "FI": 18,
    "FR": 27,
    "GB": 22,
    "IE": 22,
    "IT": 27,
    "LU": 20,
    "NL": 18,
    "NO": 15,
    "PL": 28,
    "PT": 25,
    "SE": 24,
}
_IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
_IBAN_NOISE = re.compile(r"[\s\-.]+")

#: Words that say nothing about *which* organisation it is.
_GENERIC_WORDS = frozenset(
    {
        "abteilung",
        "deutsche",
        "deutscher",
        "deutschland",
        "gesellschaft",
        "germany",
        "gruppe",
        "holding",
        "international",
        "kundenservice",
        "limited",
        "service",
        "services",
        "verwaltung",
        "zentrale",
    }
)
_MIN_WORD = 7  # a shared word must be at least this long to count as distinctive
_MIN_COMPOUND_PART = 8  # "beitragsservice" inside "rundfunkbeitragsservice"
_PAYEE_MATCH = 80.0


@dataclass(frozen=True)
class ScamFinding:
    """A reason to double-check a payment demand before paying.

    ``known_ibans``/``known_payees`` are what was seen before for ``known_party_name`` (the sender
    itself, or a look-alike organisation for ``similar_party_iban``).
    """

    kind: FindingKind
    message: str
    party_id: str
    iban: str | None = None
    payee: str | None = None
    known_party_id: str | None = None
    known_party_name: str | None = None
    known_ibans: tuple[str, ...] = ()
    known_payees: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        """Stable identity of the finding (for the ``scam`` Idea's fingerprint)."""
        return "|".join((self.kind, self.party_id, self.iban or "", self.payee or ""))


@dataclass
class PaymentHistory:
    """IBANs and payee names previously seen for one party."""

    ibans: set[str] = field(default_factory=set)
    payees: set[str] = field(default_factory=set)


# --------------------------------------------------------------------------------------------------
# IBAN
# --------------------------------------------------------------------------------------------------


def normalize_iban(iban: str) -> str:
    """``"de89 3704-0044 0532 0130 00"`` → ``"DE89370400440532013000"``."""
    return _IBAN_NOISE.sub("", iban).upper()


#: An IBAN as printed: country, check digits, then groups of letters/digits with optional spaces.
_IBAN_IN_TEXT = re.compile(r"\b[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]){11,30}")


def ibans_in_text(text: str) -> list[str]:
    """The valid IBANs printed in ``text`` (normalised, in order, without repeats).

    A match may run on into the next word ("… 4556 60 BIC"), so the longest prefix with a valid
    checksum is taken.
    """
    found: list[str] = []
    for match in _IBAN_IN_TEXT.finditer(text):
        value = normalize_iban(match.group(0))
        for end in range(min(len(value), 34), 14, -1):
            candidate = value[:end]
            if iban_valid(candidate):
                if candidate not in found:
                    found.append(candidate)
                break
    return found


def iban_from_page(read: str, page_text: str) -> str | None:
    """The IBAN printed on the page that the model most likely meant, when its reading is invalid.

    Long digit runs are easy to misread ("0004 4556 60" as "00044556660"); the text layer is exact.
    Only a printed IBAN of the same country and at least 85 % similar is taken, so a letter that
    really prints a wrong IBAN stays flagged.
    """
    return _closest(normalize_iban(read), ibans_in_text(page_text))


def _closest(value: str, candidates: Iterable[str]) -> str | None:
    """The candidate IBAN of ``value``'s country that is most alike to it (at least 85 %)."""
    best: tuple[float, str] | None = None
    for candidate in candidates:
        if candidate[:2] != value[:2]:
            continue
        score = fuzz.ratio(candidate, value)
        if score >= 85 and (best is None or score > best[0]):
            best = (score, candidate)
    return best[1] if best else None


def _misread(iban: str, known: Iterable[str]) -> bool:
    """An IBAN failing its checksum that is almost one of the ``known`` ones: that account with a
    misprinted or misread digit, not another account."""
    return not iban_valid(iban) and _closest(iban, known) is not None


def iban_valid(iban: str) -> bool:
    """Whether ``iban`` has a valid shape, known-country length and ISO 13616 mod-97 checksum."""
    value = normalize_iban(iban)
    if not _IBAN_SHAPE.match(value):
        return False
    expected = IBAN_LENGTHS.get(value[:2])
    if expected is not None and len(value) != expected:
        return False
    rearranged = value[4:] + value[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    return int(digits) % 97 == 1


def format_iban(iban: str) -> str:
    """Groups of four characters, as printed on letters."""
    value = normalize_iban(iban)
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))


# --------------------------------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------------------------------


def _words(name: str) -> list[str]:
    return utils.default_process(name).split()


def names_similar(a: str, b: str, *, ignore: Iterable[str] = ()) -> bool:
    """Whether two organisation names look alike (a scammer imitating a known sender).

    They share a distinctive word — at least seven letters, not a generic word, not in ``ignore``
    (e.g. the person's own town) and not the last word of *both* names (usually the town) — or a long
    word of one is part of a compound of the other (``Beitragsservice`` / ``Rundfunkbeitragsservice``).
    """
    words_a, words_b = _words(a), _words(b)
    skip = _GENERIC_WORDS | {word.casefold() for word in ignore}
    if not words_a or not words_b:
        return False
    for word in set(words_a) & set(words_b):
        both_last = word == words_a[-1] == words_b[-1]
        if len(word) >= _MIN_WORD and word not in skip and not both_last:
            return True
    return _compound_overlap(words_a, words_b, skip) or _compound_overlap(words_b, words_a, skip)


def _compound_overlap(parts: Sequence[str], compounds: Sequence[str], skip: frozenset[str]) -> bool:
    return any(
        len(part) >= _MIN_COMPOUND_PART and part not in skip and part != compound and part in compound
        for part in parts
        for compound in compounds
    )


def _payee_matches(payee: str, known: Iterable[str]) -> bool:
    wanted = utils.default_process(payee)
    return any(
        fuzz.token_set_ratio(wanted, utils.default_process(name)) >= _PAYEE_MATCH
        or names_similar(payee, name)
        for name in known
    )


# --------------------------------------------------------------------------------------------------
# History & findings
# --------------------------------------------------------------------------------------------------


def payment_history(store: Store, party: Party, *, exclude_doc_id: str | None = None) -> PaymentHistory:
    """What a party is known to use: its learned IBANs and the payees of its letters paying to them.

    Only IBANs that passed these checks are learned (``Party.ibans``), so a suspicious account never
    becomes "known", however many letters ask for it.
    """
    known = {normalize_iban(iban) for iban in party.ibans if iban}
    history = PaymentHistory(ibans=set(known))
    for document in store.list_documents(party_id=party.id, include_deleted=True):
        payment = document.payment
        if document.id == exclude_doc_id or payment is None or not payment.payee:
            continue
        if payment.iban is None or normalize_iban(payment.iban) in known:
            history.payees.add(payment.payee)
    return history


def _address_words(store: Store) -> frozenset[str]:
    return frozenset(_words(store.get_profile().address))


def payment_mismatch(
    store: Store, party: Party, payment: PaymentDetails, *, exclude_doc_id: str | None = None
) -> ScamFinding | None:
    """A reason to double-check ``payment`` (demanded by ``party``), or ``None``.

    In order: an IBAN the party never used before although it has used others; for a party without
    payment history, an IBAN different from the ones of a look-alike organisation; a payee name
    unlike the party and its earlier payees; an IBAN failing its checksum. The checksum comes last,
    so it never hides the other signs (a scammer's letter can carry a mistyped account too); an
    invalid IBAN that is almost a known one is that account misread, not a different account.
    ``exclude_doc_id`` leaves the document being checked out of the history.
    """
    iban = normalize_iban(payment.iban) if payment.iban else None
    history = payment_history(store, party, exclude_doc_id=exclude_doc_id)
    if iban is not None:
        if iban in history.ibans:
            return None
        if history.ibans:
            if not _misread(iban, history.ibans):
                return _changed(party, iban, payment.payee, history)
        else:
            look_alike = _look_alike_conflict(store, party, iban, payment.payee, exclude_doc_id)
            if look_alike is not None:
                return look_alike
    if (
        payment.payee
        and history.payees
        and not _payee_matches(payment.payee, [party.name, *party.aliases, *history.payees])
    ):
        return _payee_changed(party, iban, payment.payee, history)
    if iban is not None and not iban_valid(iban):
        return _invalid(party, iban, payment.payee)
    return None


def _look_alike_conflict(
    store: Store, party: Party, iban: str, payee: str | None, exclude_doc_id: str | None
) -> ScamFinding | None:
    ignore = _address_words(store)
    for other in store.list_parties():
        if other.id == party.id:
            continue
        if not any(names_similar(name, other.name, ignore=ignore) for name in (party.name, *party.aliases)):
            continue
        history = payment_history(store, other, exclude_doc_id=exclude_doc_id)
        if history.ibans and iban not in history.ibans and not _misread(iban, history.ibans):
            known = ", ".join(format_iban(value) for value in sorted(history.ibans))
            return ScamFinding(
                kind="similar_party_iban",
                message=(
                    f"Possible scam: “{party.name}” asks you to pay to {format_iban(iban)}, but "
                    f"“{other.name}”, which has a similar name, used {known} before. Check the sender "
                    "using contact details you already have before paying."
                ),
                party_id=party.id,
                iban=iban,
                payee=payee,
                known_party_id=other.id,
                known_party_name=other.name,
                known_ibans=tuple(sorted(history.ibans)),
                known_payees=tuple(sorted(history.payees)),
            )
    return None


def _invalid(party: Party, iban: str, payee: str | None) -> ScamFinding:
    return ScamFinding(
        kind="invalid_iban",
        message=(
            f"The IBAN {format_iban(iban)} is not a valid account number (its check digits are wrong). "
            "It may be misprinted, misread or fake — compare it with the letter and ask the sender before paying."
        ),
        party_id=party.id,
        iban=iban,
        payee=payee,
    )


def _changed(party: Party, iban: str, payee: str | None, history: PaymentHistory) -> ScamFinding:
    known = ", ".join(format_iban(value) for value in sorted(history.ibans))
    return ScamFinding(
        kind="iban_changed",
        message=(
            f"Possible scam: this letter asks you to pay to {format_iban(iban)}, but “{party.name}” used "
            f"{known} before. Check with the sender using contact details you already have before paying."
        ),
        party_id=party.id,
        iban=iban,
        payee=payee,
        known_party_id=party.id,
        known_party_name=party.name,
        known_ibans=tuple(sorted(history.ibans)),
        known_payees=tuple(sorted(history.payees)),
    )


def _payee_changed(party: Party, iban: str | None, payee: str, history: PaymentHistory) -> ScamFinding:
    known = ", ".join(f"“{name}”" for name in sorted(history.payees))
    return ScamFinding(
        kind="payee_changed",
        message=(
            f"Possible scam: the money should go to “{payee}”, but payments to “{party.name}” went to "
            f"{known} before. Check with the sender before paying."
        ),
        party_id=party.id,
        iban=iban,
        payee=payee,
        known_party_id=party.id,
        known_party_name=party.name,
        known_ibans=tuple(sorted(history.ibans)),
        known_payees=tuple(sorted(history.payees)),
    )
