"""How a payment is made: a transfer the person sends, or money that moves without them (a SEPA direct
debit the sender collects, money coming in). Mirrored by ``web/src/lib/payments.ts``.

Policy (ADR 0007):

* **A to-do is a direct debit** when its own words (title, action, description) name one — German
  or English wording, :data:`DEBIT_WORDS` — unless its action asks for a transfer.
* **A letter's sentence speaks of a direct debit** (:func:`debit_in_sentence`) when it names one —
  the same words, plus the split verbs "buchen … ab" and "ziehen … ein" — unless it names a debit
  that failed (a *Rücklastschrift*: after one, the person transfers) or asks for a transfer
  (a SEPA mandate offered as the alternative). A transfer the sentence waves off ("eine Überweisung
  ist nicht nötig") asks for none.
* **The reference to type** into a transfer (:func:`payment_reference`) is the letter's reference
  without a leading label word such as "Kassenzeichen": the payee's bookkeeping matches the number,
  and the label only takes room in the 140 characters.

Limits: wording is matched, not understood — a sentence that names a debit in words this list
doesn't know reads as a transfer; one that names a debit and a transfer in some other way reads as
a debit (no code; the safe side, SPEC §GiroCode).
"""

from __future__ import annotations

import re

from ordnung.models import Item

#: A direct debit in a to-do's words or a letter's sentence (German and English wording). "Einzug"
#: alone is left out: in a tenancy it is moving in.
DEBIT_WORDS = re.compile(
    r"direct debit|debited|collected automatically|sufficient funds|lastschrift|bankeinzug|abbuch|abgebucht"
    r"|eingezogen|einzieh|mandatsreferenz|gläubiger-?id|kontodeckung",
    re.I,
)
_TRANSFER_WORDS = re.compile(r"\btransfer|überweis", re.I)
#: The split verbs of a debit, their particle closing the clause: "Den Betrag buchen wir am 15.10.
#: ab", "Wir ziehen den Beitrag … von Ihrem Konto ein (Mandatsreferenz …)".
_SPLIT_DEBIT = re.compile(
    r"\b(?:buche|buchen|bucht)\b.{0,80}?\bab\b(?=\s*(?:[,;:!?()]|\.(?!\d)|$))"
    r"|\b(?:ziehe|ziehen|zieht)\b.{0,80}?\bein\b(?=\s*(?:[,;:!?()]|\.(?!\d)|$))",
    re.I | re.S,
)
#: A debit that failed: the bank returned it, or it couldn't be collected (in the same clause).
_FAILED_DEBIT = re.compile(
    r"rücklastschrift|zurückgegeben|zurückgebucht|zurückgerufen|nicht\b[^,.;:]{0,40}?"
    r"(?:eingelöst|eingezogen|abgebucht|einziehen|abbuchen)|returned|could not be (?:collected|debited)",
    re.I | re.S,
)
_NEGATION = r"(?:nicht|nichts|kein\w*|not|no|never)"
_TRANSFER = r"(?:überweis\w*|transfer\w*)"
#: A transfer the sentence waves off: a negation up to three words before it or four after it.
_NO_TRANSFER = re.compile(
    rf"\b{_NEGATION}\b(?:\W+\w+){{0,3}}?\W+{_TRANSFER}|{_TRANSFER}(?:\W+\w+){{0,4}}?\W+{_NEGATION}\b",
    re.I,
)
#: A label a letter prints before its reference (module policy).
_REFERENCE_LABEL = re.compile(
    r"^(?:kassenzeichen|aktenzeichen|az\.?|buchungszeichen|verwendungszweck|zahlungsreferenz"
    r"|referenz(?:nummer)?|reference|ref\.?|vorgang(?:snummer)?|beitragsnummer"
    r"|(?:rechnungs|kunden|vertrags|mitglieds|vorgangs)-?(?:nummer|nr\.?)|rechnung(?:\s+nr\.?)?"
    r"|(?:invoice|customer)(?:\s+(?:no\.?|number))?)(?:\s*[:#]\s*|\s+)",
    re.I,
)


def is_direct_debit(item: Item) -> bool:
    """The sender collects this payment itself (SEPA direct debit): nothing to transfer."""
    text = " ".join(part for part in (item.title, item.action, item.description) if part)
    return bool(DEBIT_WORDS.search(text)) and not _TRANSFER_WORDS.search(item.action or "")


def is_collected_or_incoming(item: Item) -> bool:
    """A payment the person doesn't make: a direct debit the sender collects, or money coming in."""
    return item.kind == "payment" and (item.direction == "in" or is_direct_debit(item))


def debit_in_sentence(sentence: str) -> bool:
    """``sentence`` (a letter's words) says the sender collects the money by direct debit (policy)."""
    if not (DEBIT_WORDS.search(sentence) or _SPLIT_DEBIT.search(sentence)):
        return False
    if _FAILED_DEBIT.search(sentence):
        return False
    return not (_TRANSFER_WORDS.search(sentence) and not _NO_TRANSFER.search(sentence))


def payment_reference(reference: str) -> str:
    """``reference`` without leading label words ("Kassenzeichen: 5126 0184 5122" → "5126 0184 5122");
    unchanged when no digit would be left."""
    value = reference.strip()
    while match := _REFERENCE_LABEL.match(value):
        rest = value[match.end() :].strip()
        if not any(char.isdigit() for char in rest):
            break
        value = rest
    return value
