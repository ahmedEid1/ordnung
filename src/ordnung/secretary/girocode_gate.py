"""When a payment gets a GiroCode — a short written policy (ADR 0007), decided by code.

A GiroCode (:mod:`ordnung.girocode`) pre-fills a transfer in the person's banking app; they still
check it there and confirm it with their TAN — Ordnung never pays (ADR 0006). A wrong code is worse
than none: a scanned IBAN or reference is not typed, so nobody looks at it closely either. A payment
to-do gets a code only when all of these hold, checked in this order; the first that fails is the
reason the person reads:

1. **It is a transfer the person makes** — not money coming in, not a direct debit the sender
   collects, and not a payment whose own sentence in the letter speaks of a direct debit
   (``Lastschrift``, ``eingezogen``, "buchen … ab" …, :func:`ordnung.payments.debit_in_sentence`;
   a returned debit or a sentence asking for a transfer is none): the app's wording follows the
   to-do's words, but a code makes paying easy, and a transfer next to a direct debit pays twice.
2. **It is still to be paid** — open, snoozed or missed; not marked paid or set aside, and not on a
   letter in the trash.
3. **The letter shows no scam signs** (:meth:`~ordnung.secretary.ledger.Ledger.scam_reasons`):
   hidden text, scam-like warnings, an IBAN or payee unlike what the sender — or an organisation with
   a look-alike name — used before. An attacker's IBAN with valid check digits on a letter that looks
   like a known sender's is exactly this case. Nor does its IBAN appear on another letter with scam
   signs (in the trash too): a scam letter teaches its sender's IBANs like any other, so a follow-up
   asking for the same account looks clean on its own. The person's *I checked — it's genuine* changes
   none of this: it brings the letter's reminders back
   (:meth:`~ordnung.secretary.ledger.Ledger.shows_scam_signs`), but a check never unlocks a code (ADR 0012).
4. **It is the payment to make from this letter** — not an invoice payment a payment reminder took
   over (pay once, from the reminder), not an e-mail's payment its attached bill asks for too (pay
   once, from the bill: :meth:`~ordnung.secretary.ledger.Ledger.is_covered_by_attachment`), and not
   one of several: a letter's bank details are read once
   per letter, and when it asks for several transfers its reference may belong to only one of them.
   A one-off payment must be the letter's only open one-off transfer — a new monthly amount the same
   letter sets (the advance payments a utility statement adjusts, § 560 Abs. 4 BGB) is paid by
   standing order and doesn't compete; a recurring payment gets a code only when the letter asks
   for no other transfer, open or paid.
5. **The details are complete and well-formed** — euro, an amount, an IBAN that passes
   :func:`~ordnung.money.iban.inspect_iban`, a payee's name, and the limits of the standard
   (:func:`~ordnung.girocode.epc_payload`: an account outside the EEA would need a BIC, which Ordnung
   doesn't read; an RF reference must have the right check digits).
6. **Every value is grounded** (ADR 0003) — the amount is stated by a sentence found in the letter's
   text layer (``verified`` evidence); the IBAN is printed in the text layer, or is one of the
   sender's learned IBANs that another of its letters — not in the trash, without scam signs — asks
   for too; the reference is printed, whole, in the text layer (not the start or end of a longer
   number: "2026-0815" is not "2026-0815-77"). A value read by AI from a photo (``model_read``), or
   not found in the letter — an amount the person typed or changed included — needs the person to
   compare the details with the letter first (the paper, for a photo; ``check_letter``). Their
   confirmation records the exact values they saw — payee, IBAN, reference and amount — and holds
   only while all four stay the same: reading the letter again differently, or changing the amount,
   asks again. Nothing else the person does to the to-do (confirming or moving its date) vouches for
   its amount.
7. **The person has compared a payment to this payee and IBAN before** — confirmed *These match the
   letter* for a payment to the same IBAN (as :func:`normalize_iban` writes it, so its spelling on the
   letter doesn't matter) under the same payee name (case and spacing aside; between two letters of the
   same sender, give or take a legal form), on a letter from the same sender when both letters have one
   (:func:`known_account`). Until then the first code to a payee waits for the person to compare the
   payee, IBAN, amount and reference with the letter, however well point 6 grounds them: a PDF's text
   layer can say something its page doesn't show (a font whose glyphs draw other digits than its text
   reads, a line clipped under a visible one), and the check for text without ink
   (:mod:`ordnung.ingest.text`) is one layer, not a guarantee. The IBAN alone is not enough:
   an account the person confirmed for one payee says nothing about a letter that names another payee
   or comes from another sender — a crafted letter's text layer could otherwise borrow it. A new IBAN
   under a familiar name is a new account too. Only the person's comparison counts — not *Mark as paid*,
   which says money left but not to which account (it may have been typed from the page by hand), not
   an IBAN the sender's letters taught, and not the model; a comparison made before this rule existed
   is the same act and counts. A to-do's own comparison vouches for the values it saw through point 6
   (``checked``); once the letter is read again with another amount or reference — the same to-do or a
   new one — it counts as an earlier payment to the account, like another letter's. The comparison goes
   with its letter: once that letter is deleted for good, the account is new again. Later codes to the
   account follow points 1–6 alone: the amount and the reference change with every letter, so comparing
   them once would vouch for nothing on the next one; they stay grounded letter by letter, and what a
   later letter's text layer could still change is how much goes, or with which reference, to an account
   the person confirmed — or, naming that payee and IBAN in full, borrow the account for a letter from
   no sender or the same one.

The reference a code carries is the letter's without a leading label word ("Kassenzeichen …",
:func:`ordnung.payments.payment_reference`), checked and shown as such. A refusal of the standard's
own limits (:class:`ordnung.girocode.GiroCodeError`) reads on after "No code:" and ends with what to
do instead.

Deliberately not decided here:

* The payee's name is not grounded: the payer's bank checks it against the account holder of the
  IBAN before the transfer (verification of payee, Art. 5c Regulation (EU) No 260/2012) and warns
  when they differ.
* Confirming against the paper letter shows the letter was read right, not that the account belongs
  to the sender (a scam letter matches its own paper), so it never teaches the sender's IBANs and
  never overrides a scam sign.

Limits: a first letter from a sender Ordnung has never seen is checked only for look-alike names
(there is no history to compare with); a letter asking for several one-off payments gets no code,
even when its reference fits all of them; debit wording is matched, not understood
(:mod:`ordnung.payments`); a letter wrongly flagged as a scam keeps its IBAN from codes until it is
deleted for good — and a letter with scam signs deleted for good (the app's Delete) no longer blocks
its IBAN on other letters: Ordnung keeps nothing of a letter deleted for good, not even its IBAN
(docs/privacy.md, "Delete means delete"), so a later letter asking for that account is judged on
its own, like a first letter from a new sender. A payment without a reference gets a code without
one; the Pay panel then says to add the letter's reference, if it names one, in the banking app.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from ordnung import girocode
from ordnung.db.store import Store
from ordnung.ingest.verify import parse_amounts
from ordnung.models import (
    Document,
    GiroCode,
    GiroCodeBlock,
    GiroCodeBlocked,
    GiroCodeReady,
    Grounding,
    Item,
    ItemStatus,
    Page,
    Party,
    TransferField,
    TransferValues,
)
from ordnung.money.iban import INVALID_IBAN_ADVICE, inspect_iban
from ordnung.payments import debit_in_sentence, is_direct_debit, payment_reference
from ordnung.secretary.ledger import Ledger
from ordnung.secretary.scam import format_iban, normalize_iban, payment_mismatch, same_payee

#: The activity entry that records the transfer details the person compared with the paper letter
#: (``ref_type="item"``; ``data`` holds the :class:`~ordnung.models.TransferValues` they confirmed).
CHECKED = "payment.checked"

ScamKind = Literal["iban_changed", "similar_party_iban", "payee_changed", "scam_iban", "other"]
_STILL_TO_PAY: frozenset[ItemStatus] = frozenset({"open", "snoozed", "missed"})
_GROUNDED: frozenset[Grounding] = frozenset({"verified", "user"})
_FIELD_NAMES: dict[TransferField, str] = {"amount": "amount", "iban": "IBAN", "reference": "reference"}
_TOKENS = re.compile(r"[^\W_]+")
#: Marks that join the parts of one printed number or reference ("0184-5122", "OA/VW", "12.345").
_JOINERS = frozenset("-‐‑–—/._")


@dataclass(frozen=True)
class ScamSign:
    """The scam sign that blocks a code: the IBAN or payee check's finding, or any other sign."""

    kind: ScamKind
    party: str | None = None
    look_alike: str | None = None
    payee: str | None = None
    #: the other letter with scam signs that asks for the same IBAN (``scam_iban``)
    letter: str | None = None
    #: the person checked the letter with its sender (*I checked — it's genuine*): still no code (ADR 0012)
    checked: bool = False


@dataclass(frozen=True)
class TransferFacts:
    """Everything the policy looks at for one payment to-do (gathered by :func:`transfer_facts`)."""

    item_id: str
    status: ItemStatus = "open"
    incoming: bool = False
    direct_debit: bool = False
    #: the sentence the payment was read from speaks of a direct debit
    debit_in_letter: bool = False
    trashed: bool = False
    #: the title of the payment reminder that took this payment over
    replaced_by: str | None = None
    #: the title of the bill attached to this e-mail that asks for the same payment
    attached_bill: str | None = None
    #: the letter's other open payments to make
    other_transfers: int = 0
    scam: ScamSign | None = None
    party: str | None = None
    currency: str | None = "EUR"
    amount: float | None = None
    amount_grounding: Grounding = "unverified"
    payee: str | None = None
    iban: str | None = None
    iban_grounding: Grounding = "unverified"
    reference: str | None = None
    reference_grounding: Grounding = "unverified"
    #: the values the person last compared with the paper letter
    checked: TransferValues | None = None
    #: the person compared a payment to this payee and IBAN with its letter before (point 7)
    known_account: bool = False

    @property
    def values(self) -> TransferValues:
        """The details a code would carry, as the person compares them."""
        return TransferValues(payee=self.payee, iban=self.iban, reference=self.reference, amount=self.amount)


# --------------------------------------------------------------------------------------------------
# The policy (pure)
# --------------------------------------------------------------------------------------------------


def decide(facts: TransferFacts) -> GiroCode:
    """The GiroCode for a payment, or why there is none (module policy, points 1–7 in order)."""
    blocked = _not_payable(facts) or _unsafe(facts) or _not_this_one(facts) or _incomplete(facts)
    if blocked is not None:
        return blocked
    try:
        payload = girocode.epc_payload(
            girocode.Transfer(
                name=facts.payee or "", iban=facts.iban or "", amount=facts.amount, reference=facts.reference
            )
        )
    except girocode.GiroCodeError as exc:
        return _blocked(facts, "invalid", f"No code: {_reads_on(str(exc))} Copy the details by hand.")
    to_check = _to_check(facts)
    first = not facts.known_account
    confirmed = facts.checked is not None and same_values(facts.checked, facts.values)
    if (to_check or first) and not confirmed:
        return GiroCodeBlocked(
            item_id=facts.item_id,
            reason="check_letter",
            message=_check_message(facts, to_check, first=first),
            to_check=to_check,
            values=facts.values,
            first_payment=first,
        )
    return GiroCodeReady(item_id=facts.item_id, payload=payload, checked=bool(to_check) or first)


def _blocked(facts: TransferFacts, reason: GiroCodeBlock, message: str) -> GiroCodeBlocked:
    return GiroCodeBlocked(item_id=facts.item_id, reason=reason, message=message)


def _reads_on(sentence: str) -> str:
    """``sentence`` continuing "No code: …" — its first word lower-cased, unless it is an acronym
    ("IBAN") or a quote."""
    first, second = sentence[:1], sentence[1:2]
    return sentence[0].lower() + sentence[1:] if first.isupper() and not second.isupper() else sentence


def _not_payable(facts: TransferFacts) -> GiroCodeBlocked | None:
    """Points 1 and 2: a transfer the person makes, still to be paid."""
    if facts.incoming:
        return _blocked(facts, "incoming", "No code: this is money coming to you.")
    if facts.direct_debit:
        who = facts.party or "the sender"
        return _blocked(
            facts,
            "direct_debit",
            f"No code: {who} collects this by direct debit — there is nothing to transfer.",
        )
    if facts.debit_in_letter:
        return _blocked(
            facts,
            "direct_debit",
            "No code: the letter says this is collected by direct debit (Lastschrift), so a transfer "
            "could pay it twice. Check your bank statement first.",
        )
    if facts.trashed:
        return _blocked(facts, "settled", "No code: this letter is in the trash.")
    if facts.status == "done":
        return _blocked(facts, "settled", "No code: you marked this as paid.")
    if facts.status not in _STILL_TO_PAY:
        return _blocked(facts, "settled", "No code: you set this to-do aside.")
    return None


def _not_this_one(facts: TransferFacts) -> GiroCodeBlocked | None:
    """Point 4: the payment to make from this letter."""
    if facts.replaced_by is not None:
        return _blocked(
            facts,
            "replaced",
            f"No code: the payment reminder “{facts.replaced_by}” took over this payment — pay once, "
            "with the reminder's details.",
        )
    if facts.attached_bill is not None:
        return _blocked(
            facts,
            "replaced",
            f"No code: the bill attached to this e-mail, “{facts.attached_bill}”, asks for this payment — "
            "pay once, with the bill's details.",
        )
    if facts.other_transfers:
        return _blocked(
            facts,
            "several",
            "No code: this letter asks for more than one payment, and its reference may belong to only "
            "one of them. Copy the details by hand.",
        )
    return None


def _unsafe(facts: TransferFacts) -> GiroCodeBlocked | None:
    """Point 3: no scam signs."""
    sign = facts.scam
    if sign is None:
        return None
    sender = sign.party or "the sender"
    ask = "Check with them using contact details you already have, not the ones in this letter."
    if sign.checked:  # the check asked for below was made: say why there is still no code
        message = (
            "No code for a letter that showed signs of a scam, even after you checked it with the sender: "
            "copy the details into your banking app by hand."
        )
    elif sign.kind == "iban_changed":
        message = f"No code: this IBAN is not the one {sender} used before. {ask}"
    elif sign.kind == "similar_party_iban":
        message = (
            f"No code: “{sign.look_alike}”, whose name is like this sender's, used another IBAN before. "
            "Check who sent this letter first, using contact details you already have."
        )
    elif sign.kind == "scam_iban":
        message = (
            f"No code: this IBAN is also in “{sign.letter}”, a letter that shows signs of a scam. "
            "Check with the sender using contact details you already have, not the ones in this letter."
        )
    elif sign.kind == "payee_changed":
        message = (
            f"No code: the money would go to “{sign.payee}”, but payments to {sender} went to someone "
            f"else before. {ask}"
        )
    else:
        message = (
            "No code: this letter shows signs of a scam. Check with the sender using contact details "
            "you already have, not the ones in this letter."
        )
    return _blocked(facts, "scam", message)


def _incomplete(facts: TransferFacts) -> GiroCodeBlocked | None:
    """Point 5 (the standard's own limits are checked when the payload is built)."""
    if (facts.currency or "EUR").upper() != "EUR":
        return _blocked(
            facts, "currency", f"No code: GiroCodes are for euro transfers, and this is in {facts.currency}."
        )
    if facts.amount is None:
        return _blocked(facts, "no_amount", "No code: the letter doesn't say how much to pay.")
    if not facts.iban:
        return _blocked(facts, "no_iban", "No code: the letter gives no IBAN to transfer to.")
    check = inspect_iban(facts.iban)
    if not check.valid:
        problems = " ".join(check.problems)
        return _blocked(
            facts,
            "invalid_iban",
            f"No code: {format_iban(facts.iban)} is not a valid IBAN. {problems} {INVALID_IBAN_ADVICE}",
        )
    if not facts.payee or not girocode.clean_text(facts.payee):
        return _blocked(facts, "no_payee", "No code: the letter doesn't name the account holder to pay.")
    return None


def _to_check(facts: TransferFacts) -> list[TransferField]:
    """Point 6: the details not grounded by the letter's text layer (or the person)."""
    found: list[TransferField] = []
    if facts.amount_grounding not in _GROUNDED:
        found.append("amount")
    if facts.iban_grounding not in _GROUNDED:
        found.append("iban")
    if facts.reference and facts.reference_grounding not in _GROUNDED:
        found.append("reference")
    return found


def _check_message(facts: TransferFacts, fields: Sequence[TransferField], *, first: bool) -> str:
    grounding = {
        "amount": facts.amount_grounding,
        "iban": facts.iban_grounding,
        "reference": facts.reference_grounding,
    }
    photo = [field for field in fields if grounding[field] == "model_read"]
    missing = [field for field in fields if grounding[field] != "model_read"]
    # the paper only for a letter read from a photo: a PDF's pages are the letter itself
    letter = "the paper letter" if photo else "the letter"
    if first:
        compared = (
            "the payee, IBAN, amount and reference" if facts.reference else "the payee, IBAN and amount"
        )
        # what is true whatever else happened: the person may have paid the account before, unseen
        source = "a letter from this sender" if facts.party else "its letter"
        why = f"you haven't compared a payment to this payee and IBAN with {source} before"
        if fields:
            why += ", and " + _grounding_reasons(photo, missing)
        return f"No code yet: {why}. Compare {compared} with {letter}, then confirm."
    it = "it" if len(fields) == 1 else "them"
    return f"No code yet: {_grounding_reasons(photo, missing)}. Compare {it} with {letter}, then confirm."


def _grounding_reasons(photo: Sequence[TransferField], missing: Sequence[TransferField]) -> str:
    """Why values need comparing: "the IBAN was read by AI from a photo and the amount wasn't found …"."""
    parts = []
    if photo:
        parts.append(f"{_names(photo)} {'was' if len(photo) == 1 else 'were'} read by AI from a photo")
    if missing:
        verb = "wasn't" if len(missing) == 1 else "weren't"
        parts.append(f"{_names(missing)} {verb} found in the letter's text")
    return " and ".join(parts)


def _names(fields: Sequence[TransferField]) -> str:
    names = [f"the {_FIELD_NAMES[field]}" for field in fields]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def same_values(a: TransferValues, b: TransferValues) -> bool:
    """Whether two sets of transfer details are the same payment (spacing and case aside)."""
    return _key(a) == _key(b)


def _key(values: TransferValues) -> tuple[str, str, str, str]:
    amount = "" if values.amount is None else f"{values.amount:.2f}"
    return (
        girocode.clean_text(values.payee or ""),
        normalize_iban(values.iban or ""),
        girocode.clean_text(values.reference or ""),
        amount,
    )


# --------------------------------------------------------------------------------------------------
# Grounding
# --------------------------------------------------------------------------------------------------


def value_grounding(value: str, pages: Sequence[Page], *, whole: bool = True) -> Grounding:
    """Where ``value`` (an IBAN or a reference) is printed: ``verified`` on a page of the letter's
    own text layer, ``model_read`` only in an AI transcription, else ``unverified``.

    The value's letters and digits must equal a run of whole words of the page (spaces, dashes and
    other marks between them aside, case aside), so a short reference never counts as found inside a
    longer number. ``whole``: the printed value must also start and end there — it doesn't run on
    through a dash, slash or dot, or into another group of digits one space away on the same line —
    so a reference cut short is no match ("2026-0815" in "2026-0815-77", "5126 0184" in "5126 0184
    5122"). An IBAN needs no such care: its length and check digits already refuse a cut-off one.
    """
    wanted = "".join(_TOKENS.findall(value.casefold()))
    if not wanted:
        return "unverified"
    found: Grounding = "unverified"
    for page in pages:
        if page.text_source not in ("text", "transcript") or not _printed(wanted, page.text, whole):
            continue
        if page.text_source == "text":
            return "verified"
        found = "model_read"
    return found


def _printed(wanted: str, text: str, whole: bool) -> bool:
    folded = text.casefold()
    tokens = list(_TOKENS.finditer(folded))
    words = [token.group() for token in tokens]
    for start, word in enumerate(words):
        if not wanted.startswith(word):
            continue
        joined, end = "", start
        while end < len(words) and len(joined) < len(wanted):
            joined += words[end]
            end += 1
        if joined == wanted and not (
            whole and (_runs_on(folded, tokens, start - 1) or _runs_on(folded, tokens, end - 1))
        ):
            return True
    return False


def _runs_on(text: str, tokens: Sequence[re.Match[str]], left: int) -> bool:
    """Whether the printed value continues from ``tokens[left]`` into the next token (see
    :func:`value_grounding`)."""
    if left < 0 or left + 1 >= len(tokens):
        return False
    before, after = tokens[left], tokens[left + 1]
    gap = text[before.end() : after.start()]
    if gap and all(char in _JOINERS for char in gap):
        return True
    return gap == " " and before.group().isdigit() and after.group().isdigit()


def amount_grounding(item: Item) -> Grounding:
    """``verified`` when a sentence found in the letter's text layer states the amount; ``model_read``
    when the letter was read from a photo (its evidence is only in the AI transcription); else
    ``unverified`` — also for an amount the person typed or changed: only their comparison with the
    paper letter (:func:`record_check`) vouches for it, never ``item.grounding``, which is about the
    to-do's date."""
    if item.amount is not None and any(
        evidence.grounding == "verified"
        and any(abs(value - item.amount) < 0.005 for value in parse_amounts(evidence.quote))
        for evidence in item.evidence
    ):
        return "verified"
    return (
        "model_read"
        if any(evidence.grounding == "model_read" for evidence in item.evidence)
        else "unverified"
    )


def amount_confirmed(store: Store, item: Item) -> bool:
    """The amount of a letter's payment is grounded as point 6 wants it: stated by a sentence found in
    the text layer, or compared by the person with the paper letter (their last check, at this amount).
    The weekly session's *Pay this week* uses it, so it never calls an amount confirmed that the Pay
    panel still asks to compare for its own sake. (The first payment to an account asks to compare every
    value, point 7: that is about the account, not a sign that the amount is in doubt.)"""
    if item.amount is None or amount_grounding(item) == "verified":
        return True
    checked = last_check(store, item.id)
    return checked is not None and checked.amount is not None and abs(checked.amount - item.amount) < 0.005


def debit_in_letter(item: Item) -> bool:
    """The sentence ``item`` was read from speaks of a direct debit (policy point 1)."""
    return any(debit_in_sentence(evidence.quote) for evidence in item.evidence)


def _asks_for(document: Document, iban: str) -> bool:
    return document.payment is not None and normalize_iban(document.payment.iban or "") == iban


def known_iban(ledger: Ledger, party: Party | None, iban: str, doc_id: str) -> bool:
    """``iban`` is one of the sender's learned IBANs and another of its letters — not in the trash,
    without scam signs — asks for it too (policy point 6)."""
    if party is None or iban not in {normalize_iban(value) for value in party.ibans}:
        return False
    return any(
        other.id != doc_id
        and other.party_id == party.id
        and _asks_for(other, iban)
        and not ledger.scam_reasons(other)
        for other in ledger.documents.values()
    )


def scam_letter_with(store: Store, ledger: Ledger, iban: str, doc_id: str) -> Document | None:
    """Another letter (in the trash too) with scam signs that asks for ``iban`` (policy point 3)."""
    return next(
        (
            other
            for other in store.list_documents(include_deleted=True)
            if other.id != doc_id and _asks_for(other, iban) and ledger.scam_reasons(other)
        ),
        None,
    )


# --------------------------------------------------------------------------------------------------
# Facts from the store
# --------------------------------------------------------------------------------------------------


def _is_transfer_todo(item: Item) -> bool:
    return (
        item.kind == "payment"
        and item.direction != "in"
        and not is_direct_debit(item)
        and not debit_in_letter(item)
    )


def _competes(ledger: Ledger, item: Item, other: Item) -> bool:
    """``other``, a to-do of the same letter, is another transfer the letter's reference may be for
    (policy point 4): for a one-off payment another open one-off transfer, for a recurring one any
    other transfer not set aside."""
    if other.id == item.id or not _is_transfer_todo(other) or ledger.is_superseded_by_reminder(other):
        return False
    if item.recurrence is None:
        return other.recurrence is None and other.status in _STILL_TO_PAY
    return other.status in _STILL_TO_PAY or other.status == "done"


def _scam_sign(store: Store, ledger: Ledger, document: Document, party: Party | None) -> ScamSign | None:
    if not ledger.scam_reasons(document):
        iban = normalize_iban(document.payment.iban or "") if document.payment else ""
        other = scam_letter_with(store, ledger, iban, document.id) if iban else None
        if other is None:
            return None
        return ScamSign(
            kind="scam_iban", party=party.name if party else None, letter=other.title or other.filename
        )
    checked = document.id in ledger.scam_checked
    if party is not None and document.payment is not None:
        finding = payment_mismatch(store, party, document.payment, exclude_doc_id=document.id)
        if finding is not None and finding.kind != "invalid_iban":
            return ScamSign(
                kind=finding.kind,
                party=party.name,
                look_alike=finding.known_party_name,
                payee=finding.payee,
                checked=checked,
            )
    return ScamSign(kind="other", party=party.name if party else None, checked=checked)


@dataclass(frozen=True)
class ComparedPayment:
    """A payment the person compared with its letter (*These match the letter*): the values they saw and
    the sender of that letter (``None``: a letter matched to no sender, or one no longer there)."""

    item_id: str
    values: TransferValues
    party_id: str | None


def compared_accounts(store: Store) -> dict[str, tuple[ComparedPayment, ...]]:
    """The payments the person compared with their letters, by IBAN (policy point 7). Only their own
    confirmation counts, and it goes with its letter when that is deleted for good
    (:meth:`~ordnung.db.store.Store.delete_document`)."""
    senders: dict[str, str | None] = {}
    found: dict[str, list[ComparedPayment]] = {}
    for entry in store.list_activity(None, kinds=[CHECKED]):
        iban = entry.data.get("iban")
        if entry.ref_type != "item" or not entry.ref_id or not isinstance(iban, str) or not iban:
            continue
        doc_id = entry.data.get("doc_id")
        if isinstance(doc_id, str) and doc_id not in senders:
            document = store.get_document(doc_id)
            senders[doc_id] = document.party_id if document is not None else None
        compared = ComparedPayment(
            item_id=entry.ref_id,
            values=TransferValues.model_validate(entry.data),
            party_id=senders.get(doc_id) if isinstance(doc_id, str) else None,
        )
        found.setdefault(normalize_iban(iban), []).append(compared)
    return {iban: tuple(payments) for iban, payments in found.items()}


def _payee_key(payee: str | None) -> str:
    return "".join(girocode.clean_text(payee or "").casefold().split())


def known_account(
    compared: Sequence[ComparedPayment], values: TransferValues, party_id: str | None, item_id: str
) -> bool:
    """Whether the person compared a payment to this payee and IBAN before (policy point 7): another
    comparison of the same IBAN under the same payee name, from the same sender when both letters have
    one. The name is the same one, case and spacing aside; only between two letters of the same sender
    may it differ by a legal form (:func:`~ordnung.secretary.scam.same_payee`) — anything looser would
    lend the account to another payee. This to-do's own comparison of exactly these values doesn't count:
    it vouches for them as ``checked`` does."""
    payee = _payee_key(values.payee)
    if not payee or not values.payee:
        return False
    for earlier in compared:
        if earlier.item_id == item_id and same_values(earlier.values, values):
            continue
        if party_id is not None and earlier.party_id is not None and earlier.party_id != party_id:
            continue
        if _payee_key(earlier.values.payee) == payee or (
            party_id is not None
            and earlier.party_id == party_id
            and same_payee(earlier.values.payee or "", values.payee)
        ):
            return True
    return False


def last_check(store: Store, item_id: str) -> TransferValues | None:
    """The transfer details the person last compared with the paper letter (``None``: never)."""
    entry = store.last_activity("item", item_id, [CHECKED])
    return TransferValues.model_validate(entry.data) if entry is not None else None


def transfer_facts(
    store: Store,
    ledger: Ledger,
    document: Document,
    item: Item,
    siblings: Sequence[Item],
    compared: Mapping[str, Sequence[ComparedPayment]],
) -> TransferFacts:
    """What the policy needs to know about ``item`` of ``document`` (``siblings``: the letter's to-dos;
    ``compared``: :func:`compared_accounts`)."""
    party = store.get_party(document.party_id) if document.party_id else None
    payment = document.payment
    pages = store.list_pages(document.id)
    iban = normalize_iban(payment.iban) if payment and payment.iban else None
    reference = payment_reference(payment.reference) if payment and payment.reference else None
    reminder = (
        ledger.covering_reminders().get(document.id) if ledger.is_superseded_by_reminder(item) else None
    )
    bill = ledger.covering_attachments().get(item.id) if ledger.is_covered_by_attachment(item) else None
    others = [other for other in siblings if _competes(ledger, item, other)]
    iban_grounding: Grounding = "unverified"
    if iban is not None:
        iban_grounding = (
            "verified"
            if known_iban(ledger, party, iban, document.id)
            else value_grounding(iban, pages, whole=False)
        )
    facts = TransferFacts(
        item_id=item.id,
        status=item.status,
        incoming=item.direction == "in",
        direct_debit=is_direct_debit(item),
        debit_in_letter=debit_in_letter(item),
        trashed=document.deleted_at is not None,
        replaced_by=(reminder.title or reminder.filename) if reminder is not None else None,
        attached_bill=(bill.title or bill.filename) if bill is not None else None,
        other_transfers=len(others),
        scam=_scam_sign(store, ledger, document, party),
        party=party.name if party else None,
        currency=item.currency,
        amount=item.amount,
        amount_grounding=amount_grounding(item),
        payee=payment.payee if payment else None,
        iban=iban,
        iban_grounding=iban_grounding,
        reference=reference,
        reference_grounding=value_grounding(reference, pages) if reference else "unverified",
        checked=last_check(store, item.id),
        known_account=False,
    )
    if iban is not None:
        facts = replace(
            facts,
            known_account=known_account(compared.get(iban, ()), facts.values, document.party_id, item.id),
        )
    return facts


def document_girocodes(
    store: Store, document: Document, items: Sequence[Item], today: date
) -> list[GiroCode]:
    """One GiroCode (or reason) per payment to-do of ``document``."""
    payments = [item for item in items if item.kind == "payment"]
    if not payments:
        return []
    ledger = Ledger(store, today)
    compared = compared_accounts(store)
    return [decide(transfer_facts(store, ledger, document, item, items, compared)) for item in payments]


def item_girocode(store: Store, item: Item, today: date) -> GiroCode | None:
    """The GiroCode of one payment to-do (``None``: it is no payment of a letter)."""
    document = store.get_document(item.doc_id) if item.doc_id else None
    if document is None or item.kind != "payment":
        return None
    items = store.list_items(doc_id=document.id)
    return decide(
        transfer_facts(store, Ledger(store, today), document, item, items, compared_accounts(store))
    )


class CheckRefused(Exception):
    """Why the person's comparison with the paper letter can't unlock a code (plain words)."""


NOT_A_PAYMENT = "This to-do isn't a payment from a letter."
NOTHING_TO_COMPARE = "There is nothing to compare for this payment."
DETAILS_CHANGED = "The payment details changed since you looked at them. Please compare them again."


def record_check(store: Store, item: Item, values: TransferValues, today: date) -> GiroCode:
    """Record that the person compared ``values`` with the paper letter and return the new code.

    Refused unless the payment is waiting for exactly this (``check_letter``) and ``values`` are the
    details it currently has — so a confirmation never covers details the person didn't see, and
    never unlocks a code the policy refuses for any other reason.
    """
    current = item_girocode(store, item, today)
    if current is None:
        raise CheckRefused(NOT_A_PAYMENT)
    if not isinstance(current, GiroCodeBlocked) or current.reason != "check_letter":
        raise CheckRefused(NOTHING_TO_COMPARE if isinstance(current, GiroCodeReady) else current.message)
    if current.values is None or not same_values(values, current.values):
        raise CheckRefused(DETAILS_CHANGED)
    store.log_activity(
        CHECKED,
        f"You compared the transfer details of “{item.title}” with the letter",
        ref_type="item",
        ref_id=item.id,
        # the letter's id too: deleting the letter deletes this entry, even after the to-do is gone
        data={**current.values.model_dump(), "doc_id": item.doc_id},
    )
    updated = item_girocode(store, item, today)
    assert updated is not None  # the same payment as a moment ago
    return updated
