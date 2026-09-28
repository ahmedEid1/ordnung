"""Linking (SPEC § 8 stage 6): connect a read document to the ledger — deterministic, no model.

* **Party** — identifier match (account-like references and the sender's own identifiers) →
  exact name/alias → fuzzy name (rapidfuzz ``token_set_ratio`` ≥ 92) → new party with the
  deterministic id ``content_id("pty", normalised name)``. New identifiers, aliases, contact details
  and (unless the payment looks suspicious) the payee IBAN are merged into the party.
* **Case (thread)** — by reference: Aktenzeichen, Rechnungsnummer, Kundennummer, Vertragsnummer,
  Steuernummer, Beitragsnummer (a dunning letter prefers the Rechnungsnummer); else a new case. An
  e-mail and the attachments it brought share one thread where their references allow it
  (:func:`email_family_case`): each letter threads by its **own** references first — so a payment
  reminder attached to an e-mail still joins its invoice's thread — and joins its family's thread only
  instead of opening a new one. An e-mail read before its attachment that is still alone in its thread
  follows the attachment into the thread the attachment's references found, and the thread it leaves
  is deleted (:func:`follow_attachment`).
* **Contracts** — an extracted contract is upserted; a change (price increase …) or a cancellation
  confirmation is linked to the party's contract and recorded, never applied (§ 21 "no silent
  closing"): the triggers engine turns it into an Idea and only the person's click changes it.
* **Dunning** — linked to the invoice's thread. Which payment a reminder takes over is worked out on
  read (:func:`reminder_covers`), so deleting the reminder (or it turning out to be a scam) brings the
  invoice's payment back, and a reminder read before its invoice still covers it. It takes over the
  invoice's one-off payments only, never a recurring one (arrears are not the advance payments still
  to come). Nothing is closed.

Every function here writes through the :class:`~ordnung.db.store.Store` and is meant to run inside
the pipeline's single ledger transaction.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from rapidfuzz import fuzz, utils

from ordnung.db.store import Store, normalize_identifier
from ordnung.ids import content_id
from ordnung.ingest.attachments import attached_to, email_source, is_email
from ordnung.models import (
    PAYMENT_DEMAND_KINDS,
    Case,
    Contract,
    Document,
    DocumentExtraction,
    Evidence,
    ExtractedParty,
    Identifier,
    Item,
    Party,
    PaymentDetails,
)
from ordnung.rules import RuleContext, compute_contract
from ordnung.secretary.scam import ScamFinding, iban_valid, normalize_iban, payment_mismatch
from ordnung.trace import facts
from ordnung.trace.facts import MAX_CANDIDATES, PartyDecision
from ordnung.trace.spans import NO_SPAN, Span

ReferenceKind = Literal[
    "aktenzeichen",
    "rechnungsnummer",
    "kundennummer",
    "vertragsnummer",
    "steuernummer",
    "beitragsnummer",
    "account",
    "personal",
    "other",
]

FUZZY_MIN = 92.0
#: Below this plain similarity a fuzzy match must share two words ("Finanzamt" ≠ "Finanzamt X").
FUZZY_GUARD = 70.0
MIN_IDENTIFIER_CHARS = 5

CASE_PREFERENCE: tuple[ReferenceKind, ...] = (
    "aktenzeichen",
    "rechnungsnummer",
    "kundennummer",
    "vertragsnummer",
    "steuernummer",
    "beitragsnummer",
)
#: References that identify the person's account with one sender (stored on the party).
PARTY_REFERENCE_KINDS: frozenset[ReferenceKind] = frozenset(
    {"kundennummer", "vertragsnummer", "steuernummer", "beitragsnummer", "account"}
)
#: A case found by these may belong to another party (an Inkasso letter about an invoice).
CROSS_PARTY_KINDS: frozenset[ReferenceKind] = frozenset({"aktenzeichen", "rechnungsnummer"})

# First matching rule wins; keywords of ≤ 4 letters must equal the whole label.
_LABEL_RULES: tuple[tuple[ReferenceKind, tuple[str, ...]], ...] = (
    (
        "personal",
        (
            "steuerid",
            "identifikationsnummer",
            "idnr",
            "sozialversicherung",
            "rentenversicherungsnummer",
            "svnummer",
            "versichertennummer",
            "iban",
            "bic",
        ),
    ),
    ("steuernummer", ("steuernummer", "steuernr", "stnr", "taxnumber")),
    ("beitragsnummer", ("beitragsnummer", "beitragskonto")),
    ("rechnungsnummer", ("rechnung", "invoice", "rgnr", "belegnr", "belegnummer")),
    ("kundennummer", ("kunden", "customer", "kdnr")),
    (
        "vertragsnummer",
        ("vertrag", "contract", "police", "policy", "versicherungsschein", "versicherungsnummer"),
    ),
    (
        "aktenzeichen",
        (
            "aktenzeichen",
            "az",
            "geschaeftszeichen",
            "kassenzeichen",
            "vorgang",
            "fallnummer",
            "casenumber",
            "filenumber",
            "reference",
            "unserzeichen",
        ),
    ),
    ("account", ("mitglied", "member", "personalnummer", "matrikel", "zaehlernummer")),
)
_LABEL_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_CHANGE_TYPES_TO_RECORD = frozenset(
    {"price_increase", "price_decrease", "terms_change", "termination_by_provider"}
)


@dataclass
class LinkResult:
    """What a document was linked to, plus warnings for the document."""

    party: Party | None = None
    case: Case | None = None
    contract: Contract | None = None
    scam: ScamFinding | None = None
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------------------------------


def _label_key(label: str) -> str:
    folded = unicodedata.normalize("NFKC", label).casefold().translate(_LABEL_TRANSLIT)
    return "".join(char for char in folded if char.isalnum())


def reference_kind(label: str) -> ReferenceKind:
    """What a printed reference label denotes (``"Kunden-Nr."`` → ``kundennummer``)."""
    key = _label_key(label)
    for kind, keywords in _LABEL_RULES:
        if any(key == word if len(word) <= 4 else word in key for word in keywords):
            return kind
    return "other"


def _usable(value: str) -> bool:
    return len(normalize_identifier(value)) >= MIN_IDENTIFIER_CHARS


def party_identifiers(sender: ExtractedParty | None, references: Iterable[Identifier]) -> list[Identifier]:
    """Identifiers that belong on the sender's party: its own and the account-like references."""
    candidates = [*(sender.identifiers if sender else []), *references]
    chosen: dict[str, Identifier] = {}
    for identifier in candidates:
        kind = reference_kind(identifier.label)
        own = sender is not None and identifier in sender.identifiers
        if kind == "personal" or not (own or kind in PARTY_REFERENCE_KINDS) or not _usable(identifier.value):
            continue
        chosen.setdefault(normalize_identifier(identifier.value), identifier)
    return list(chosen.values())


def case_references(references: Iterable[Identifier], *, prefer_invoice: bool = False) -> list[Identifier]:
    """References usable for threading, in preference order (a dunning letter: invoice number first)."""
    order = list(CASE_PREFERENCE)
    if prefer_invoice:
        order.remove("rechnungsnummer")
        order.insert(0, "rechnungsnummer")
    ranked = [
        (order.index(kind), index, ref)
        for index, ref in enumerate(references)
        if (kind := reference_kind(ref.label)) in order and normalize_identifier(ref.value)
    ]
    return [ref for _, _, ref in sorted(ranked, key=lambda entry: entry[:2])]


# --------------------------------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------------------------------


def normalise_name(name: str) -> str:
    """Casefolded, whitespace-collapsed name (the basis of party ids)."""
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def party_id_for(name: str) -> str:
    """Deterministic id of a party first seen with ``name``."""
    return content_id("pty", normalise_name(name))


def name_score(a: str, b: str) -> float:
    """Fuzzy similarity of two names (``token_set_ratio`` of the processed names, 0–100).

    A subset match of a single shared word ("Finanzamt" vs "Finanzamt Musterstadt") scores 0 unless
    the plain similarity is high as well.
    """
    left, right = utils.default_process(a), utils.default_process(b)
    score = fuzz.token_set_ratio(left, right)
    shared = set(left.split()) & set(right.split())
    if len(shared) < 2 and fuzz.ratio(left, right) < FUZZY_GUARD:
        return 0.0
    return float(score)


def party_scores(parties: Iterable[Party], name: str) -> list[tuple[float, Party]]:
    """Every party with a similarity above 0 to ``name`` (its best name or alias), best first (ties
    keep the parties' order)."""
    scored = [
        (max(name_score(name, candidate) for candidate in (party.name, *party.aliases)), party)
        for party in parties
    ]
    return sorted((entry for entry in scored if entry[0] > 0), key=lambda entry: -entry[0])


def find_party_fuzzy(parties: Iterable[Party], name: str) -> Party | None:
    """The party whose name or alias is most similar to ``name`` (score ≥ :data:`FUZZY_MIN`)."""
    scored = party_scores(parties, name)
    return scored[0][1] if scored and scored[0][0] >= FUZZY_MIN else None


@dataclass(frozen=True)
class PartyMatch:
    """How a sender was matched (:func:`match_party`): the party (``None``: none yet), the rule that
    decided, the similarity of a fuzzy match, the kind of the identifier that matched, and the closest
    other parties with their scores."""

    party: Party | None
    decision: PartyDecision
    score: float | None = None
    reference_kind: str | None = None
    candidates: tuple[tuple[str, float], ...] = ()


def match_party(store: Store, sender: ExtractedParty | None, references: Sequence[Identifier]) -> PartyMatch:
    """:func:`resolve_party`, saying how: identifier → exact name/alias → fuzzy name → none."""
    for identifier in party_identifiers(sender, references):
        party = store.find_party_by_identifier(identifier.value)
        if party is not None:
            return PartyMatch(party, "identifier", reference_kind=reference_kind(identifier.label))
    if sender is None or not sender.name.strip():
        return PartyMatch(None, "none")
    exact = store.find_parties_by_name(sender.name)
    if exact:
        return PartyMatch(exact[0], "name")
    scored = party_scores(store.list_parties(), sender.name)
    best = scored[0] if scored and scored[0][0] >= FUZZY_MIN else None
    others = tuple((party.id, score) for score, party in scored if best is None or party.id != best[1].id)
    if best is None:
        return PartyMatch(None, "new", candidates=others[:MAX_CANDIDATES])
    return PartyMatch(best[1], "similar_name", score=best[0], candidates=others[:MAX_CANDIDATES])


def resolve_party(
    store: Store, sender: ExtractedParty | None, references: Sequence[Identifier]
) -> Party | None:
    """An existing party for the sender: identifier → exact name/alias → fuzzy name; else ``None``."""
    return match_party(store, sender, references).party


def _merge_fields(
    party: Party, sender: ExtractedParty | None, identifiers: Sequence[Identifier]
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    known = {normalize_identifier(identifier.value) for identifier in party.identifiers}
    new = [identifier for identifier in identifiers if normalize_identifier(identifier.value) not in known]
    if new:
        fields["identifiers"] = [*party.identifiers, *new]
    if sender is None:
        return fields
    names = {normalise_name(name) for name in (party.name, *party.aliases)}
    if sender.name.strip() and normalise_name(sender.name) not in names:
        fields["aliases"] = [*party.aliases, sender.name.strip()]
    for attribute in ("address", "email", "phone", "website"):
        if getattr(party, attribute) is None and getattr(sender, attribute):
            fields[attribute] = getattr(sender, attribute)
    if party.kind == "other" and sender.kind != "other":
        fields["kind"] = sender.kind
    return fields


def ensure_party(store: Store, extraction: DocumentExtraction, *, trace: Span = NO_SPAN) -> Party | None:
    """Resolve the sender's party (creating it if new) and merge the new details into it.

    ``trace`` is described with how the sender was matched (:func:`ordnung.trace.facts.party_match`).
    """
    sender = extraction.sender
    identifiers = party_identifiers(sender, extraction.references)
    match = match_party(store, sender, extraction.references)
    party, decision = match.party, match.decision
    if party is None:
        if sender is None or not sender.name.strip():
            trace.set(**facts.party_match("none", party_id=None))
            return None
        party = store.get_party(party_id_for(sender.name))  # first seen under this name, renamed since
        decision = "name" if party is not None else "new"
        party = party or store.add_party(
            id=party_id_for(sender.name),
            name=sender.name.strip(),
            kind=sender.kind,
            address=sender.address,
            email=sender.email,
            phone=sender.phone,
            website=sender.website,
        )
    trace.set(
        **facts.party_match(
            decision,
            party_id=party.id,
            score=match.score,
            reference_kind=match.reference_kind,
            candidates=match.candidates,
        )
    )
    fields = _merge_fields(party, sender, identifiers)
    return store.update_party(party.id, **fields) if fields else party


def check_payment(
    store: Store, party: Party | None, payment: PaymentDetails | None, *, doc_id: str, trace: Span = NO_SPAN
) -> tuple[Party | None, ScamFinding | None]:
    """Scam-check a payment demand; a clean, valid IBAN becomes one of the party's known IBANs."""
    if party is None or payment is None or not (payment.iban or payment.payee):
        return party, None
    finding = payment_mismatch(store, party, payment, exclude_doc_id=doc_id)
    iban = normalize_iban(payment.iban) if payment.iban else None
    known = {normalize_iban(value) for value in party.ibans}
    added = finding is None and bool(iban) and iban_valid(iban or "") and iban not in known
    if added and iban:
        party = store.update_party(party.id, ibans=[*party.ibans, iban])
    trace.set(
        **facts.payment_check(
            finding=finding.kind if finding else None,
            iban_valid=iban_valid(iban) if iban else None,
            iban_known=iban in known,
            iban_added=added,
        )
    )
    return party, finding


# --------------------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------------------


def thread_case(
    store: Store,
    party: Party | None,
    extraction: DocumentExtraction,
    *,
    family: Case | None = None,
    trace: Span = NO_SPAN,
) -> Case:
    """The thread a document belongs to: found by reference, else ``family`` (the thread of the
    e-mail it came with, or of that e-mail's attachments), else created (deterministic id)."""
    references = case_references(extraction.references, prefer_invoice=extraction.kind == "dunning")
    for reference in references:
        case = store.find_case_by_reference(reference.value)
        same_party = party is None or case is None or case.party_id in (None, party.id)
        if case is not None and (same_party or reference_kind(reference.label) in CROSS_PARTY_KINDS):
            trace.set(**facts.thread("reference", case.id, reference_kind(reference.label)))
            return case
    if family is not None:
        trace.set(**facts.thread("email", family.id, None))
        return family
    title = extraction.case_title.strip() or extraction.title
    key = normalize_identifier(references[0].value) if references else normalise_name(title)
    case_id = content_id("cas", party.id if party else "", key)
    first_kind = reference_kind(references[0].label) if references else None
    existing = store.get_case(case_id)
    if existing is not None:
        trace.set(**facts.thread("same_thread", existing.id, first_kind))
        return existing
    trace.set(**facts.thread("new", case_id, first_kind))
    return store.add_case(
        id=case_id,
        title=title,
        party_id=party.id if party else None,
        reference=references[0].value if references else None,
        area=extraction.area,
    )


def email_family_case(store: Store, document: Document) -> Case | None:
    """The thread of the e-mail family ``document`` belongs to, once another member is linked — the
    thread :func:`thread_case` falls back to when the letter's own references find none.

    For an attachment (``source="email:<id>"``): its e-mail's thread, else that of a sibling
    attachment linked before it; for an e-mail: the thread of its first attachment linked before it.
    Letters in the trash don't count. ``None`` while none of them is linked.
    """
    parent_id = attached_to(document)
    if parent_id is not None:
        parent = store.get_document(parent_id)
        family = [parent] if parent is not None else []
        siblings = store.list_documents(source=email_source(parent_id))
    elif is_email(document):
        family, siblings = [], store.list_documents(source=email_source(document.id))
    else:
        return None
    family += sorted(siblings, key=lambda doc: (doc.created_at, doc.id))
    for member in family:
        if member.id == document.id or member.deleted_at is not None or member.case_id is None:
            continue
        case = store.get_case(member.case_id)
        if case is not None:
            return case
    return None


def follow_attachment(store: Store, document: Document, case: Case) -> Document | None:
    """An attachment was threaded into ``case``: its e-mail follows it there when the e-mail is alone
    in a thread of its own (it was read first and its references found nothing better). Its to-dos
    move with it, and the thread it leaves — empty now — is deleted, so its reference (a Kundennummer)
    no longer draws later letters into an empty thread. An e-mail whose thread holds another letter, a
    contract or a draft stays where it is. Returns the e-mail if it moved."""
    parent_id = attached_to(document)
    parent = store.get_document(parent_id) if parent_id else None
    if parent is None or parent.deleted_at is not None or parent.case_id in (None, case.id):
        return None
    old = parent.case_id
    others = [doc for doc in store.list_documents(case_id=old, include_deleted=True) if doc.id != parent.id]
    if (
        others
        or any(contract.case_id == old for contract in store.list_contracts())
        or store.list_drafts(case_id=old)
    ):
        return None
    for item in store.list_items(doc_id=parent.id):
        if item.case_id == old:
            store.update_item(item.id, case_id=case.id)
    moved = store.update_document(parent.id, case_id=case.id)
    if not store.list_items(case_id=old):  # a to-do the person added to the thread keeps it
        store.delete_case(old)
    return moved


# --------------------------------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------------------------------

_CONTRACT_TERM_FIELDS = (
    "name",
    "category",
    "customer_number",
    "concluded_date",
    "start_date",
    "initial_term_months",
    "renewal_term_months",
    "notice_value",
    "notice_unit",
    "notice_basis",
    "end_date",
    "cost_amount",
    "cost_interval",
    "is_consumer",
    "is_basic_supply",
)


def customer_number(extraction: DocumentExtraction) -> str | None:
    """The contract's customer/contract number: from the contract record, else the references."""
    if extraction.contract and extraction.contract.customer_number:
        return extraction.contract.customer_number
    for reference in extraction.references:
        if reference_kind(reference.label) in ("kundennummer", "vertragsnummer"):
            return reference.value
    return None


def contract_id_for(party: Party | None, category: str, number: str | None, doc_id: str) -> str:
    """Deterministic contract id: party, category and customer number (or the source document)."""
    basis = normalize_identifier(number) if number else doc_id
    return content_id("ctr", party.id if party else "", category, basis)


def _contract_values(extraction: DocumentExtraction | None) -> dict[str, Any] | None:
    """The contract fields an extraction states (``None`` if it states no contract)."""
    if extraction is None or extraction.contract is None:
        return None
    values = {name: getattr(extraction.contract, name) for name in _CONTRACT_TERM_FIELDS}
    values["customer_number"] = customer_number(extraction)
    return values


def _unedited(existing: Contract, values: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """The fields to write: empty ones, and — when the last extraction is known — those the person
    has not changed since (their value still equals what was extracted before)."""
    return {
        name: value
        for name, value in values.items()
        if getattr(existing, name) is None
        or (previous is not None and getattr(existing, name) == previous.get(name))
    }


def _entered_terms(existing: Contract, fields: dict[str, Any]) -> list[Evidence]:
    """The notice terms the person entered on the contract's card (a quote ``confirmed by the
    person``), kept when its letter is read again — unless this reading rewrites them."""
    if any(name in fields for name in ("notice_value", "notice_unit", "notice_basis")):
        return []
    return [evidence for evidence in existing.evidence if evidence.grounding == "user"]


def upsert_contract(
    store: Store,
    *,
    document: Document,
    extraction: DocumentExtraction,
    party: Party | None,
    case: Case | None,
    evidence: list[Evidence],
    rule_ctx: RuleContext,
    postal_buffer_days: int,
    trace: Span = NO_SPAN,
) -> Contract | None:
    """Create or refresh the contract a document states, then recompute its dates.

    Reprocessing the contract's own letter refreshes the fields the person has not edited; a
    contract known from elsewhere only gets its empty fields filled.
    """
    values = _contract_values(extraction)
    if values is None:
        return None
    contract_id = contract_id_for(party, values["category"], values["customer_number"], document.id)
    existing = store.get_contract(contract_id)
    if existing is None and party is not None:
        existing = store.find_contract(party.id, values["customer_number"], values["category"])
    if existing is None:
        contract = store.add_contract(
            id=contract_id,
            source_doc_id=document.id,
            evidence=evidence,
            party_id=party.id if party else None,
            case_id=case.id if case else None,
            area=extraction.area,
            **values,
        )
        trace.set(**facts.contract("created", contract.id))
    elif existing.source_doc_id == document.id:
        previous = _contract_values(store.get_extraction(document.id))
        fields = _unedited(existing, values, previous)
        contract = store.update_contract(
            existing.id, evidence=[*evidence, *_entered_terms(existing, fields)], **fields
        )
        trace.set(**facts.contract("refreshed", contract.id))
    else:
        contract = store.update_contract(existing.id, **_unedited(existing, values, None))
        trace.set(**facts.contract("filled", contract.id))
    computed = compute_contract(
        contract.terms(party.kind if party else None), rule_ctx, postal_buffer_days=postal_buffer_days
    )
    return store.update_contract(contract.id, computed=computed)


def find_changed_contract(
    store: Store, party: Party | None, extraction: DocumentExtraction
) -> Contract | None:
    """The party's contract a change or confirmation letter is about (customer number, else the only one)."""
    if party is None:
        return None
    number = customer_number(extraction)
    if number:
        found = store.find_contract(party.id, number, None)
        if found is not None:
            return found
    active = store.list_contracts(status="active", party_id=party.id)
    return active[0] if len(active) == 1 else None


def record_change(
    store: Store, contract: Contract, document: Document, extraction: DocumentExtraction
) -> None:
    """Log a contract change or cancellation confirmation; the contract itself is left untouched."""
    change = extraction.change
    kind = change.type if change else "cancellation_confirmation"
    when = f" from {change.effective_date}" if change and change.effective_date else ""
    store.log_activity(
        "contract.change",
        f"{kind.replace('_', ' ').capitalize()} for “{contract.name}”{when}",
        ref_type="contract",
        ref_id=contract.id,
        data={"doc_id": document.id, "change": change.model_dump() if change else {"type": kind}},
    )


def link_change(
    store: Store,
    *,
    document: Document,
    extraction: DocumentExtraction,
    party: Party | None,
    trace: Span = NO_SPAN,
) -> tuple[Contract | None, list[str]]:
    """Link a change or cancellation-confirmation letter to its contract and record it.

    The contract is never changed: the triggers engine turns the recorded letter into an Idea
    (special cancellation right, "Confirm cancellation?") and only the person's click changes it.
    """
    change_type = extraction.change.type if extraction.change else None
    confirmation = (
        change_type == "cancellation_confirmation" or extraction.kind == "cancellation_confirmation"
    )
    if not confirmation and change_type not in _CHANGE_TYPES_TO_RECORD:
        return None, []
    recorded = change_type or "cancellation_confirmation"
    contract = find_changed_contract(store, party, extraction)
    if contract is None:
        trace.set(**facts.contract("no_match", None, recorded))
        return None, [
            "We couldn't match this letter to one of your contracts — add the contract to track it."
        ]
    record_change(store, contract, document, extraction)
    trace.set(**facts.contract("change_recorded", contract.id, recorded))
    return contract, []


# --------------------------------------------------------------------------------------------------
# Dunning
# --------------------------------------------------------------------------------------------------

DUNNING_ITEM_NOTE = "A payment reminder (Mahnung) arrived for this invoice — pay once, not twice."


def invoice_numbers(references: Iterable[Identifier]) -> set[str]:
    """The normalised invoice numbers (Rechnungsnummern) among a letter's references."""
    return {
        normalize_identifier(reference.value)
        for reference in references
        if reference_kind(reference.label) == "rechnungsnummer"
    }


def reminder_covers(reminder: Document, other: Document) -> bool:
    """Whether the payment reminder ``reminder`` takes over the payments of ``other``: a letter of the
    same thread about the same invoice number, written before it — the invoice itself, or an earlier
    reminder. A court order about the claim counts as a reminder (:data:`PAYMENT_DEMAND_KINDS`). A later letter citing the number (a corrected invoice, "Bezug: RE-4711") is a new demand.

    Pure: callers decide which reminders count (live ones without scam signs).
    """
    if (
        reminder.kind not in PAYMENT_DEMAND_KINDS
        or reminder.direction != "incoming"
        or other.id == reminder.id
    ):
        return False
    if reminder.case_id is None or other.case_id != reminder.case_id:
        return False
    numbers = invoice_numbers(reminder.references)
    if not numbers or not any(normalize_identifier(ref.value) in numbers for ref in other.references):
        return False
    if other.kind in PAYMENT_DEMAND_KINDS:  # of two reminders, the later one is the one to pay
        return (other.doc_date or "", other.created_at) < (reminder.doc_date or "", reminder.created_at)
    # without both dates it can't be told which came first (a reminder may be read before its invoice)
    return not (other.doc_date and reminder.doc_date and other.doc_date > reminder.doc_date)


ATTACHMENT_ITEM_NOTE = (
    "The bill attached to this e-mail asks for the same payment — pay it once, as the bill says."
)


def _same_amount(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 0.005


def attachment_repeats(
    email: Document, item: Item, attachment: Document, attachment_items: Iterable[Item]
) -> bool:
    """Whether the e-mail's payment to-do ``item`` repeats a payment of ``attachment``, a letter that
    came attached to that e-mail (a bill whose e-mail says "49,99 EUR, fällig am 15.09."): one of the
    attachment's payments has the same direction and currency, and either the same amount and due date,
    or the same amount (or the e-mail names none) where both letters name the same invoice number
    (Rechnungsnummer). The attachment is the bill, so the e-mail's to-do is the one set aside.

    A different amount is never the same payment: a payment reminder e-mail with its invoice attached
    asks for the invoice's amount plus fees (the reminder takes the invoice over instead, see
    :func:`reminder_covers`).

    Pure: callers decide which letters count as the e-mail's attachments and which of their payments
    count (live letters without scam signs; payments no payment reminder took over — so the reminder
    e-mail itself never loses its to-do to the invoice it took over), so deleting the attachment brings
    the e-mail's to-do back.
    """
    if item.kind != "payment" or item.doc_id != email.id or attachment.id == email.id:
        return False
    same_bill = bool(invoice_numbers(email.references) & invoice_numbers(attachment.references))
    for other in attachment_items:
        if (
            other.kind != "payment"
            or other.doc_id != attachment.id
            or other.direction != item.direction
            or (other.currency or "EUR") != (item.currency or "EUR")
        ):
            continue
        if same_bill and (item.amount is None or _same_amount(other.amount, item.amount)):
            return True
        if _same_amount(other.amount, item.amount) and other.due_date == item.due_date:
            return True
    return False


def link_dunning(
    store: Store, case: Case, extraction: DocumentExtraction, doc_id: str, *, kind: str | None = None
) -> list[str]:
    """Warn on a payment reminder about an invoice that is already filed (its payment is never closed;
    views and triggers leave it to the reminder while the reminder is live, see :func:`reminder_covers`),
    worded by the kind the letter is filed as (``kind``, default: the reading's, :func:`reminder_warning`)."""
    numbers = invoice_numbers(extraction.references)
    if extraction.kind != "dunning" or not numbers:
        return []
    warnings = []
    for invoice in store.list_documents(case_id=case.id):
        if invoice.id == doc_id or not any(
            normalize_identifier(r.value) in numbers for r in invoice.references
        ):
            continue
        warnings.append(reminder_warning(invoice.title or invoice.filename, kind or extraction.kind))
    return [warning for warning in warnings if warning]


_REMINDER_WARNINGS: dict[str, str] = {
    "dunning": "This is a payment reminder about “{title}”, which is still open. Pay the amount asked here once — "
    "not both.",
    "court_payment_order": "This court order is about “{title}”, which is still open. If you pay, pay the amount "
    "this order asks once — not the invoice as well.",
    "enforcement_order": "This court order is about “{title}”, which is still open. If you pay, pay the amount "
    "this order asks once — not the invoice as well.",
}
"""The "pay once" warning of a letter about an open invoice, by the kind it is filed as (none for other kinds)."""
_WARNED_TITLE = re.compile(
    r"^This (?:is a payment reminder|court order is) about “(?P<title>.*)”, which is still open\. "
)


def reminder_warning(title: str, kind: str | None) -> str:
    """The "pay once" warning of a letter about the open invoice ``title``, worded for its kind (empty for a
    kind it doesn't apply to: a reminder re-filed as, say, a landlord's notice)."""
    return _REMINDER_WARNINGS.get(kind or "", "").format(title=title)


def rewarn_for_kind(warnings: Sequence[str], kind: str | None) -> list[str]:
    """A letter's warnings after it was filed as ``kind``: its "pay once" warning worded for that kind, or left
    out (review round 4 of phase 2: a reminder re-filed as a court order still said "This is a payment
    reminder")."""
    kept: list[str] = []
    for warning in warnings:
        found = _WARNED_TITLE.match(warning)
        reworded = reminder_warning(found.group("title"), kind) if found else warning
        if reworded:
            kept.append(reworded)
    return kept


# --------------------------------------------------------------------------------------------------
# Everything
# --------------------------------------------------------------------------------------------------


def _about_a_contract(extraction: DocumentExtraction) -> bool:
    """Whether a letter states a contract, or a change or confirmation that may be about one."""
    return (
        extraction.contract is not None
        or extraction.change is not None
        or extraction.kind == "cancellation_confirmation"
    )


def link_document(
    store: Store,
    *,
    document: Document,
    extraction: DocumentExtraction,
    party: Party | None,
    contract_evidence: list[Evidence],
    rule_ctx: RuleContext,
    postal_buffer_days: int,
    trace: Span = NO_SPAN,
) -> LinkResult:
    """Thread the document, link contracts/changes/dunning and scam-check its payment demand.

    ``party`` comes from :func:`ensure_party` (resolved first because the date rules need it).
    ``trace`` gets one step per decision: the payment check (when the letter asks for money), the
    thread, the contract (when the letter states one or a change) and a reminder's invoices.
    """
    result = LinkResult(party=party)
    with trace.span("link", "Thread & contract", key="links", stage="link") as links:
        if extraction.payment is not None:
            with links.span("link", "Payment check", key="payment") as step:
                result.party, result.scam = check_payment(
                    store, party, extraction.payment, doc_id=document.id, trace=step
                )
        if result.scam is not None:
            result.warnings.append(result.scam.message)
        with links.span("link", "Thread", key="thread") as step:
            result.case = thread_case(
                store, result.party, extraction, family=email_family_case(store, document), trace=step
            )
        follow_attachment(store, document, result.case)
        contract_step = links if _about_a_contract(extraction) else NO_SPAN
        with contract_step.span("link", "Contract", key="contract") as step:
            result.contract = upsert_contract(
                store,
                document=document,
                extraction=extraction,
                party=result.party,
                case=result.case,
                evidence=contract_evidence,
                rule_ctx=rule_ctx,
                postal_buffer_days=postal_buffer_days,
                trace=step,
            )
            if result.contract is None:
                result.contract, warnings = link_change(
                    store, document=document, extraction=extraction, party=result.party, trace=step
                )
                result.warnings.extend(warnings)
            if "decision" not in step.attributes:
                step.set(**facts.contract("none", None))
        if extraction.kind == "dunning":
            with links.span("link", "Payment reminder", key="reminder") as step:
                reminders = link_dunning(store, result.case, extraction, document.id, kind=document.kind)
                step.set(**facts.reminder(len(reminders)))
                result.warnings.extend(reminders)
    return result
