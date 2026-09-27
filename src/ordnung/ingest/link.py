"""Linking (SPEC § 8 stage 6): connect a read document to the ledger — deterministic, no model.

* **Party** — identifier match (account-like references and the sender's own identifiers) →
  exact name/alias → fuzzy name (rapidfuzz ``token_set_ratio`` ≥ 92) → new party with the
  deterministic id ``content_id("pty", normalised name)``. New identifiers, aliases, contact details
  and (unless the payment looks suspicious) the payee IBAN are merged into the party.
* **Case (thread)** — by reference: Aktenzeichen, Rechnungsnummer, Kundennummer, Vertragsnummer,
  Steuernummer, Beitragsnummer (a dunning letter prefers the Rechnungsnummer); else a new case.
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
from ordnung.models import (
    PAYMENT_DEMAND_KINDS,
    Case,
    Contract,
    Document,
    DocumentExtraction,
    Evidence,
    ExtractedParty,
    Identifier,
    Party,
    PaymentDetails,
)
from ordnung.rules import RuleContext, compute_contract
from ordnung.secretary.scam import ScamFinding, iban_valid, normalize_iban, payment_mismatch

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


def find_party_fuzzy(parties: Iterable[Party], name: str) -> Party | None:
    """The party whose name or alias is most similar to ``name`` (score ≥ :data:`FUZZY_MIN`)."""
    best: tuple[float, Party] | None = None
    for party in parties:
        score = max(name_score(name, candidate) for candidate in (party.name, *party.aliases))
        if score >= FUZZY_MIN and (best is None or score > best[0]):
            best = (score, party)
    return best[1] if best else None


def resolve_party(
    store: Store, sender: ExtractedParty | None, references: Sequence[Identifier]
) -> Party | None:
    """An existing party for the sender: identifier → exact name/alias → fuzzy name; else ``None``."""
    for identifier in party_identifiers(sender, references):
        party = store.find_party_by_identifier(identifier.value)
        if party is not None:
            return party
    if sender is None or not sender.name.strip():
        return None
    exact = store.find_parties_by_name(sender.name)
    if exact:
        return exact[0]
    return find_party_fuzzy(store.list_parties(), sender.name)


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


def ensure_party(store: Store, extraction: DocumentExtraction) -> Party | None:
    """Resolve the sender's party (creating it if new) and merge the new details into it."""
    sender = extraction.sender
    identifiers = party_identifiers(sender, extraction.references)
    party = resolve_party(store, sender, extraction.references)
    if party is None:
        if sender is None or not sender.name.strip():
            return None
        party = store.get_party(party_id_for(sender.name)) or store.add_party(
            id=party_id_for(sender.name),
            name=sender.name.strip(),
            kind=sender.kind,
            address=sender.address,
            email=sender.email,
            phone=sender.phone,
            website=sender.website,
        )
    fields = _merge_fields(party, sender, identifiers)
    return store.update_party(party.id, **fields) if fields else party


def check_payment(
    store: Store, party: Party | None, payment: PaymentDetails | None, *, doc_id: str
) -> tuple[Party | None, ScamFinding | None]:
    """Scam-check a payment demand; a clean, valid IBAN becomes one of the party's known IBANs."""
    if party is None or payment is None or not (payment.iban or payment.payee):
        return party, None
    finding = payment_mismatch(store, party, payment, exclude_doc_id=doc_id)
    iban = normalize_iban(payment.iban) if payment.iban else None
    known = {normalize_iban(value) for value in party.ibans}
    if finding is None and iban and iban_valid(iban) and iban not in known:
        party = store.update_party(party.id, ibans=[*party.ibans, iban])
    return party, finding


# --------------------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------------------


def thread_case(store: Store, party: Party | None, extraction: DocumentExtraction) -> Case:
    """The thread a document belongs to: found by reference, else created (deterministic id)."""
    references = case_references(extraction.references, prefer_invoice=extraction.kind == "dunning")
    for reference in references:
        case = store.find_case_by_reference(reference.value)
        same_party = party is None or case is None or case.party_id in (None, party.id)
        if case is not None and (same_party or reference_kind(reference.label) in CROSS_PARTY_KINDS):
            return case
    title = extraction.case_title.strip() or extraction.title
    key = normalize_identifier(references[0].value) if references else normalise_name(title)
    case_id = content_id("cas", party.id if party else "", key)
    existing = store.get_case(case_id)
    if existing is not None:
        return existing
    return store.add_case(
        id=case_id,
        title=title,
        party_id=party.id if party else None,
        reference=references[0].value if references else None,
        area=extraction.area,
    )


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
    elif existing.source_doc_id == document.id:
        previous = _contract_values(store.get_extraction(document.id))
        contract = store.update_contract(
            existing.id, evidence=evidence, **_unedited(existing, values, previous)
        )
    else:
        contract = store.update_contract(existing.id, **_unedited(existing, values, None))
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
    store: Store, *, document: Document, extraction: DocumentExtraction, party: Party | None
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
    contract = find_changed_contract(store, party, extraction)
    if contract is None:
        return None, [
            "We couldn't match this letter to one of your contracts — add the contract to track it."
        ]
    record_change(store, contract, document, extraction)
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


def link_document(
    store: Store,
    *,
    document: Document,
    extraction: DocumentExtraction,
    party: Party | None,
    contract_evidence: list[Evidence],
    rule_ctx: RuleContext,
    postal_buffer_days: int,
) -> LinkResult:
    """Thread the document, link contracts/changes/dunning and scam-check its payment demand.

    ``party`` comes from :func:`ensure_party` (resolved first because the date rules need it).
    """
    result = LinkResult(party=party)
    result.party, result.scam = check_payment(store, party, extraction.payment, doc_id=document.id)
    if result.scam is not None:
        result.warnings.append(result.scam.message)
    result.case = thread_case(store, result.party, extraction)
    result.contract = upsert_contract(
        store,
        document=document,
        extraction=extraction,
        party=result.party,
        case=result.case,
        evidence=contract_evidence,
        rule_ctx=rule_ctx,
        postal_buffer_days=postal_buffer_days,
    )
    if result.contract is None:
        result.contract, warnings = link_change(
            store, document=document, extraction=extraction, party=result.party
        )
        result.warnings.extend(warnings)
    result.warnings.extend(link_dunning(store, result.case, extraction, document.id, kind=document.kind))
    return result
