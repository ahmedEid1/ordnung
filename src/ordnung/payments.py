"""How a payment is made: a transfer the person sends, money paid in person (card or cash on site), or
money that moves without them (a SEPA direct debit the sender collects, money coming in). Mirrored by
``web/src/lib/payments.ts`` and ``paysOnSite`` in ``web/src/features/document/item-meta.ts``.

Policy (ADR 0007):

* **A to-do is a direct debit** when its own words (title, action, description) name one —
  :data:`DEBIT_WORDS`, German or English — unless they say the debit failed (:data:`_FAILED_DEBIT`:
  a *Rücklastschrift*, "konnte nicht eingezogen werden", "could not be debited" — after one, the
  person transfers) or its action asks for a transfer.
* **A letter's sentence speaks of a direct debit** (:func:`debit_in_sentence`) when it names one —
  the same words, a mandate's reference or the creditor's ID, the split verb "buchen … ab", or
  "einziehen" in a clause that names the account or the money ("von Ihrem Konto eingezogen", "ziehen
  den Betrag … ein"; moving in names neither: "sobald Sie eingezogen sind") — unless it says the debit
  failed, or one of its clauses asks for a transfer (a SEPA mandate offered as the alternative:
  "Sofern Sie nicht am Lastschriftverfahren teilnehmen, überweisen Sie …"). A transfer its own
  clause waves off ("eine Überweisung ist nicht nötig", "überweisen Sie nicht") asks for none.
* **A clause** ends at a comma, a full stop, ``;``, ``:``, ``!`` or ``?`` — not at the marks inside
  a number or a date ("29,90 €", "am 15.10. von Ihrem Konto").
* **The reference to type** into a transfer (:func:`payment_reference`) is the letter's reference
  without a leading label word such as "Kassenzeichen": the payee's bookkeeping matches the number,
  and the label only takes room in the 140 characters.

"Einziehen" and "Einzug" are left out of the to-do's words (in a tenancy they are moving in), and so
are the mandate's reference and the creditor's ID (a letter asking for a transfer after the mandate
ended prints them too).

Limits: wording is matched, not understood — a sentence that names a debit in words these lists
don't know reads as a transfer; one that names a debit and a transfer in some other way reads as
a debit (no code; the safe side, SPEC §GiroCode); words of a failed debit count also where they only
warn of one ("Gebühr bei Rücklastschrift").
"""

from __future__ import annotations

import re

from ordnung.models import Item

#: A direct debit in a to-do's words or a letter's sentence (German and English wording).
DEBIT_WORDS = re.compile(
    r"direct debit|debited|collected automatically|sufficient funds|lastschrift|bankeinzug|abbuch|abgebucht"
    r"|kontodeckung",
    re.I,
)
#: A debit only a letter's sentence names: the mandate's reference, the creditor's ID, the split verb
#: "buchen … ab" (its particle closing the clause: "Den Betrag buchen wir am 15.10. ab").
_SENTENCE_DEBIT = re.compile(
    r"mandatsreferenz|gläubiger-?id"
    r"|\b(?:buche|buchen|bucht)\b.{0,80}?\bab\b(?=\s*(?:[,;:!?()]|\.(?!\d)|$))",
    re.I | re.S,
)
#: "Einziehen" (collect — or move in), counted in a clause that names the account or the money.
_COLLECT = re.compile(
    r"eingezogen|einzuziehen|einzieh|\b(?:ziehe|ziehen|zieht)\b.{0,80}?\bein\s*(?:\(|$)", re.I | re.S
)
_ACCOUNT_OR_MONEY = re.compile(r"konto|account|betrag|beitrag|summe|forderung|gebühr|prämie|entgelt", re.I)
_TRANSFER_WORDS = re.compile(r"\btransfer|überweis", re.I)
#: A debit that failed: the bank returned it, or it couldn't be collected (in one clause).
_FAILED_DEBIT = re.compile(
    r"rücklastschrift|zurückgegeben|zurückgebucht|zurückgerufen|mangels\s+deckung|fehlgeschlagen"
    r"|nicht\s+gedeckt|nicht\b.{0,40}?(?:eingelöst|eingezogen|abgebucht|einziehen|abbuchen|ausgeführt|durchgeführt)"
    r"|(?:abbuchung|lastschrift|einzug).{0,40}?nicht\s+möglich"
    r"|returned|could\s+not\s+be\s+(?:collected|debited)",
    re.I | re.S,
)
#: Where a clause ends (module policy): not at a comma or full stop inside a number or a date.
_CLAUSE_END = re.compile(r"[;:!?]|(?<!\d),|,(?!\d)|(?<!\d)\.(?!\d)")
_NEGATION = r"(?:nicht|nichts|kein\w*|not|no|never|\w+n['’]t)"
_TRANSFER = r"(?:überweis\w*|transfer\w*)"
#: A transfer its clause waves off: a negation up to three words before it or four after it.
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


def _clauses(text: str) -> list[str]:
    return _CLAUSE_END.split(text)


def debit_failed(text: str) -> bool:
    """``text`` says a direct debit failed — returned by the bank, or not collected (module policy)."""
    return any(_FAILED_DEBIT.search(clause) for clause in _clauses(text))


def is_direct_debit(item: Item) -> bool:
    """The sender collects this payment itself (SEPA direct debit): nothing to transfer (policy)."""
    text = " ".join(part for part in (item.title, item.action, item.description) if part)
    return (
        bool(DEBIT_WORDS.search(text))
        and not debit_failed(text)
        and not _TRANSFER_WORDS.search(item.action or "")
    )


def is_collected_or_incoming(item: Item) -> bool:
    """A payment the person doesn't make: a direct debit the sender collects, or money coming in."""
    return item.kind == "payment" and (item.direction == "in" or is_direct_debit(item))


#: Paid in person — at the appointment, the service desk or a machine, by card or in cash (as
#: ``ON_SITE`` in ``web/src/features/document/item-meta.ts``).
_ON_SITE_WORDS = re.compile(
    r"\bon[ -]site\b|\bat the appointment\b|\bat the (?:service )?(?:desk|counter)\b|\bpayment machine\b"
    r"|\bgirocard\b|\bEC[ -]card\b|\bcash\b|\bvor Ort\b|\bin bar\b|\bbar (?:be)?zahlen\b|\bEC-Karte\b"
    r"|\bam (?:Kassen|Zahl)automaten\b|\ban der Kasse\b",
    re.I,
)


def pays_on_site(item: Item) -> bool:
    """A payment made in person (card or cash at the appointment, the desk, a machine), not by bank
    transfer: its "send by" — a transfer's day (§ 675s BGB) — means nothing, the due day is the day."""
    if item.kind != "payment" or item.direction == "in" or is_direct_debit(item):
        return False
    how = " ".join(part for part in (item.action, item.description) if part)
    return bool(_ON_SITE_WORDS.search(how)) and not _TRANSFER_WORDS.search(item.action or "")


def debit_in_sentence(sentence: str) -> bool:
    """``sentence`` (a letter's words) says the sender collects the money by direct debit (policy)."""
    clauses = _clauses(sentence)
    names_debit = (
        DEBIT_WORDS.search(sentence)
        or _SENTENCE_DEBIT.search(sentence)
        or any(_COLLECT.search(clause) and _ACCOUNT_OR_MONEY.search(clause) for clause in clauses)
    )
    if not names_debit or debit_failed(sentence):
        return False
    return not any(_TRANSFER_WORDS.search(clause) and not _NO_TRANSFER.search(clause) for clause in clauses)


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
