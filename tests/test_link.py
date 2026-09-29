"""Deterministic linking: reference labels, party resolution, case threading and contracts."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from ordnung.api.routes.contracts import notice_evidence
from ordnung.db.store import Store
from ordnung.ids import content_id
from ordnung.ingest.link import (
    case_references,
    contract_id_for,
    ensure_party,
    find_changed_contract,
    link_change,
    name_score,
    party_id_for,
    party_identifiers,
    reference_kind,
    resolve_party,
    thread_case,
    upsert_contract,
)
from ordnung.models import Contract, Document, DocumentExtraction, Evidence, ExtractedParty, Identifier
from ordnung.rules import RuleContext


def extraction(**fields: Any) -> DocumentExtraction:
    base: dict[str, Any] = {"kind": "other", "title": "Letter", "summary": "s", "explanation": "e"}
    return DocumentExtraction.model_validate(base | fields)


def sender(name: str, kind: str = "other", **fields: Any) -> dict[str, Any]:
    return {"name": name, "kind": kind, **fields}


def ref(label: str, value: str) -> Identifier:
    return Identifier(label=label, value=value)


def add_doc(store: Store, sha_char: str = "a") -> Document:
    return store.add_document(
        sha256=sha_char * 64, filename="letter.pdf", mime="application/pdf", file_path="x.pdf"
    )


# --------------------------------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Aktenzeichen", "aktenzeichen"),
        ("Az.", "aktenzeichen"),
        ("Unser Zeichen", "aktenzeichen"),
        ("Kassenzeichen", "aktenzeichen"),
        ("Rechnungsnummer", "rechnungsnummer"),
        ("Rechnungs-Nr.", "rechnungsnummer"),
        ("Invoice no.", "rechnungsnummer"),
        ("Kundennummer", "kundennummer"),
        ("Kd.-Nr.", "kundennummer"),
        ("Customer reference", "kundennummer"),
        ("Vertragsnummer", "vertragsnummer"),
        ("Versicherungsschein-Nr.", "vertragsnummer"),
        ("Steuernummer", "steuernummer"),
        ("St.-Nr.", "steuernummer"),
        ("Beitragsnummer", "beitragsnummer"),
        ("Mitgliedsnummer", "account"),
        ("Steuer-ID", "personal"),
        ("Steuerliche Identifikationsnummer", "personal"),
        ("Rentenversicherungsnummer", "personal"),
        ("IBAN", "personal"),
        ("USt-IdNr.", "other"),
        ("Ihr Zeichen", "other"),
    ],
)
def test_reference_kind(label: str, kind: str) -> None:
    assert reference_kind(label) == kind


def test_party_identifiers_keep_account_references_and_own_ids_only() -> None:
    who = ExtractedParty(name="Muster Telecom", identifiers=[ref("USt-IdNr.", "DE123456789")])
    references = [
        ref("Kundennummer", "K-778899"),
        ref("Rechnungsnummer", "R-2026-0815"),
        ref("Steuer-ID", "12 345 678 901"),
        ref("Kunden-Nr.", "K 778899"),  # same number, other spelling
        ref("Vertragsnummer", "12"),  # too short to identify anyone
    ]
    assert [i.value for i in party_identifiers(who, references)] == ["DE123456789", "K-778899"]


def test_case_references_order_and_invoice_preference() -> None:
    references = [ref("Kundennummer", "K-1"), ref("Rechnungsnummer", "R-1"), ref("Aktenzeichen", "AZ-1")]
    assert [r.value for r in case_references(references)] == ["AZ-1", "R-1", "K-1"]
    assert [r.value for r in case_references(references, prefer_invoice=True)] == ["R-1", "AZ-1", "K-1"]


# --------------------------------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------------------------------


def test_name_score_guards_single_word_subsets() -> None:
    assert name_score("Muster Telecom GmbH", "Muster Telecom") == 100
    assert name_score("Finanzamt", "Finanzamt Musterstadt") == 0
    assert name_score("Finanzamt Musterstadt", "Stadtwerke Musterstadt") < 92


def test_resolve_by_identifier_beats_a_different_name(store: Store) -> None:
    known = store.add_party(name="Muster Telecom GmbH", identifiers=[ref("Kundennummer", "K-778899")])
    other = ExtractedParty(name="MT Mobilfunk")
    assert resolve_party(store, other, [ref("Kunden-Nr.", "K 778899")]) == known


def test_resolve_by_alias_and_fuzzy_name(store: Store) -> None:
    known = store.add_party(name="Techniker Krankenkasse", aliases=["TK"])
    assert resolve_party(store, ExtractedParty(name="tk"), []) == known
    assert resolve_party(store, ExtractedParty(name="Techniker Krankenkasse (TK)"), []) == known
    assert resolve_party(store, ExtractedParty(name="AOK Krankenkasse"), []) is None


def test_ensure_party_creates_with_a_deterministic_id(store: Store) -> None:
    data = extraction(
        sender=sender("Finanzamt  Musterstadt", "tax_office", address="Steuerstraße 1"),
        references=[ref("Steuernummer", "123/456/78901")],
    )
    party = ensure_party(store, data)
    assert party is not None
    assert party.id == party_id_for("finanzamt musterstadt") == content_id("pty", "finanzamt musterstadt")
    assert party.kind == "tax_office"
    assert party.identifiers == [ref("Steuernummer", "123/456/78901")]
    assert ensure_party(store, data) == party


def test_ensure_party_merges_new_details(store: Store) -> None:
    known = store.add_party(name="Muster Telecom GmbH", identifiers=[ref("Kundennummer", "K-778899")])
    data = extraction(
        sender=sender("Muster Telecom", "telecom", email="service@muster.example"),
        references=[ref("Kundennummer", "K778899"), ref("Vertragsnummer", "V-55555")],
    )
    party = ensure_party(store, data)
    assert party is not None and party.id == known.id
    assert party.aliases == ["Muster Telecom"]
    assert party.kind == "telecom"
    assert party.email == "service@muster.example"
    assert [i.value for i in party.identifiers] == ["K-778899", "V-55555"]


def test_no_sender_and_no_identifier_means_no_party(store: Store) -> None:
    assert ensure_party(store, extraction()) is None


# --------------------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------------------


def test_thread_case_creates_then_finds_by_reference(store: Store) -> None:
    party = store.add_party(name="Muster Telecom")
    invoice = extraction(kind="invoice", case_title="Bill", references=[ref("Rechnungsnummer", "R-1")])
    case = thread_case(store, party, invoice)
    assert case.id == content_id("cas", party.id, "r1")
    assert case.reference == "R-1" and case.title == "Bill"
    dunning = extraction(
        kind="dunning", references=[ref("Aktenzeichen", "INK-9"), ref("Rechnungsnummer", "R 1")]
    )
    assert thread_case(store, party, dunning).id == case.id


def test_account_references_do_not_cross_parties(store: Store) -> None:
    first = store.add_party(name="Muster Gym")
    second = store.add_party(name="Muster Bank")
    gym_case = thread_case(store, first, extraction(references=[ref("Kundennummer", "12345")]))
    bank_case = thread_case(store, second, extraction(references=[ref("Kundennummer", "12345")]))
    assert bank_case.id != gym_case.id
    collector = store.add_party(name="Muster Inkasso")
    invoice_case = thread_case(store, first, extraction(references=[ref("Rechnungsnummer", "R-77")]))
    assert (
        thread_case(store, collector, extraction(references=[ref("Rechnungsnummer", "R-77")])) == invoice_case
    )


def test_thread_case_by_title_without_references(store: Store) -> None:
    case = thread_case(store, None, extraction(case_title="  Moving flat "))
    assert case.id == content_id("cas", "", "moving flat")
    assert thread_case(store, None, extraction(case_title="Moving  flat")) == case


# --------------------------------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------------------------------

GYM = {
    "name": "Gym",
    "category": "gym",
    "concluded_date": "2024-02-20",
    "start_date": "2024-03-01",
    "initial_term_months": 24,
    "notice_value": 1,
    "notice_unit": "months",
    "cost_amount": 29.9,
    "cost_interval": "monthly",
}


def rule_ctx() -> RuleContext:
    return RuleContext(today=date(2026, 9, 25))


def test_upsert_contract_is_deterministic_and_computed(store: Store) -> None:
    party = store.add_party(name="Muster Fitness", kind="gym")
    document = add_doc(store)
    data = extraction(contract=GYM, references=[ref("Vertragsnummer", "FIT-1")])
    contract = upsert_contract(
        store,
        document=document,
        extraction=data,
        party=party,
        case=None,
        evidence=[],
        rule_ctx=rule_ctx(),
        postal_buffer_days=4,
    )
    assert contract is not None
    assert contract.id == contract_id_for(party, "gym", "FIT-1", document.id)
    assert contract.customer_number == "FIT-1"
    assert contract.computed is not None and contract.computed.regime == "bgb309_new"


@pytest.mark.parametrize(
    ("category", "terms", "dates"),
    [
        (
            "transport",  # Deutschlandticket: "bis zum 10. eines Monats zum Ende dieses Monats"
            {"concluded_date": "2025-12-10", "start_date": "2026-01-01", "notice_basis": "end_of_month", "notice_day": 10},
            ("2026-10-10", "2026-10-31", None),
        ),
        (
            "employment",  # working student: ordinary notice after probation, before the fixed end
            {"start_date": "2026-04-01", "end_date": "2027-03-31", "notice_before_end": True, "is_consumer": False},
            ("2026-10-03", "2026-10-31", "2027-03-31"),
        ),
    ],
)  # fmt: skip
def test_upsert_contract_copies_the_notice_terms_a_period_cant_say(
    store: Store, category: str, terms: dict[str, Any], dates: tuple[str, str, str | None]
) -> None:
    """Migration 0004: the day of the month and the early notice of a fixed-term job are stored and computed."""
    document = add_doc(store)
    data = extraction(contract={"name": "Contract", "category": category, **terms})
    contract = upsert_contract(
        store,
        document=document,
        extraction=data,
        party=None,
        case=None,
        evidence=[],
        rule_ctx=RuleContext(today=date(2026, 9, 28), region="NW"),
        postal_buffer_days=4,
    )
    assert contract is not None and store.get_contract(contract.id) == contract
    assert (contract.notice_day, contract.notice_before_end) == (
        terms.get("notice_day"),
        terms.get("notice_before_end", False),
    )
    assert contract.computed is not None
    computed = contract.computed
    assert (computed.cancel_by, computed.earliest_exit, computed.current_term_end) == dates


def test_upsert_contract_never_overwrites_a_contract_from_elsewhere(store: Store) -> None:
    party = store.add_party(name="Muster Fitness", kind="gym")
    edited = store.add_contract(
        id=contract_id_for(party, "gym", "FIT-1", "x"),
        name="My gym",
        category="gym",
        party_id=party.id,
        customer_number="FIT-1",
        cost_amount=25.0,
    )
    data = extraction(contract=GYM, references=[ref("Vertragsnummer", "FIT-1")])
    contract = upsert_contract(
        store,
        document=add_doc(store),
        extraction=data,
        party=party,
        case=None,
        evidence=[],
        rule_ctx=rule_ctx(),
        postal_buffer_days=4,
    )
    assert contract is not None and contract.id == edited.id
    assert contract.name == "My gym" and contract.cost_amount == 25.0
    assert contract.start_date == "2024-03-01"  # empty fields are filled


def test_reprocessing_refreshes_only_fields_the_person_did_not_edit(store: Store) -> None:
    party = store.add_party(name="Muster Fitness", kind="gym")
    document = add_doc(store)
    first = extraction(contract=GYM, references=[ref("Vertragsnummer", "FIT-1")])
    contract = upsert_contract(
        store,
        document=document,
        extraction=first,
        party=party,
        case=None,
        evidence=[],
        rule_ctx=rule_ctx(),
        postal_buffer_days=4,
    )
    assert contract is not None
    store.update_document(document.id, extraction=first)  # what the pipeline stores after reading
    store.update_contract(contract.id, notice_value=2)  # the person corrects the notice period

    second = extraction(contract=GYM | {"cost_amount": 34.9}, references=[ref("Vertragsnummer", "FIT-1")])
    again = upsert_contract(
        store,
        document=document,
        extraction=second,
        party=party,
        case=None,
        evidence=[],
        rule_ctx=rule_ctx(),
        postal_buffer_days=4,
    )
    assert again is not None and again.id == contract.id
    assert again.cost_amount == 34.9
    assert again.notice_value == 2


def test_reprocessing_keeps_the_notice_terms_the_person_entered_as_theirs(store: Store) -> None:
    """UI audit R2-inbox-timeline-contracts-1: "Save notice period" records the terms as the person's (a
    ``user`` quote) so the card stops asking to check them; reading the letter again keeps that quote while
    their terms stand — and drops it when the reading rewrites them."""
    party = store.add_party(name="Musterbank eG", kind="bank")
    document = add_doc(store)
    no_terms = {"name": "Girokonto", "category": "bank", "cost_amount": 4.9, "cost_interval": "monthly"}
    first = extraction(contract=no_terms, references=[ref("Kontonummer", "7004")])

    def read(data: Any, quotes: list[Evidence]) -> Contract:
        contract = upsert_contract(
            store,
            document=document,
            extraction=data,
            party=party,
            case=None,
            evidence=quotes,
            rule_ctx=rule_ctx(),
            postal_buffer_days=4,
        )
        assert contract is not None
        return contract

    letter = Evidence(doc_id=document.id, quote="Kontoführung 4,90 €", grounding="verified")
    contract = read(first, [letter])
    store.update_document(document.id, extraction=first)
    entered = store.update_contract(
        contract.id, notice_value=3, notice_unit="months", notice_basis="end_of_month"
    )
    store.update_contract(contract.id, evidence=notice_evidence(entered))

    again = read(first, [letter])
    assert [(e.grounding, e.quote) for e in again.evidence] == [
        ("verified", "Kontoführung 4,90 €"),
        ("user", "three months' notice to the end of a month"),
    ]
    assert again.notice_value == 3
    # a reading that writes the notice terms itself (the person's are gone): no quote of theirs is left
    store.update_contract(contract.id, notice_value=None, notice_unit=None, notice_basis=None)
    stated = extraction(
        contract=no_terms | {"notice_value": 1, "notice_unit": "months", "notice_basis": "end_of_month"},
        references=[ref("Kontonummer", "7004")],
    )
    assert [e.grounding for e in read(stated, [letter]).evidence] == ["verified"]


def test_reading_again_never_brings_back_a_day_the_person_cleared(store: Store) -> None:
    """The Deutschlandticket's day of the month, misread and replaced on the card by a notice period (saving
    the period clears the day): reading the letter again keeps the person's terms as a whole, and doesn't put
    the letter's day back beside their period, where the earlier deadline would decide."""
    document = add_doc(store)
    terms = {"name": "Deutschlandticket", "category": "transport", "concluded_date": "2025-12-10"}
    read_day = extraction(
        contract=terms | {"start_date": "2026-01-01", "notice_basis": "end_of_month", "notice_day": 10}
    )

    def read(data: Any) -> Contract:
        contract = upsert_contract(
            store,
            document=document,
            extraction=data,
            party=None,
            case=None,
            evidence=[],
            rule_ctx=RuleContext(today=date(2026, 9, 28), region="NW"),
            postal_buffer_days=4,
        )
        assert contract is not None
        return contract

    contract = read(read_day)
    store.update_document(document.id, extraction=read_day)
    entered = store.update_contract(
        contract.id, notice_value=1, notice_unit="months", notice_basis="end_of_month", notice_day=None
    )
    store.update_contract(contract.id, evidence=notice_evidence(entered))

    again = read(read_day)
    assert (again.notice_value, again.notice_unit, again.notice_day) == (1, "months", None)
    assert [e.grounding for e in again.evidence] == ["user"]
    # the person's month decides (any time, at most a month: § 309 Nr. 9 BGB), not the letter's 10th
    assert again.computed is not None and again.computed.cancel_by != "2026-10-10"
    assert "the 10th" not in again.computed.summary


def test_change_links_to_the_only_active_contract_without_touching_it(store: Store) -> None:
    party = store.add_party(name="Muster Energie", kind="utility")
    contract = store.add_contract(name="Power", category="energy", party_id=party.id, cost_amount=80.0)
    data = extraction(
        kind="price_increase",
        change={"type": "price_increase", "effective_date": "2026-11-01", "new_amount": 95.0, "quote": "q"},
    )
    assert find_changed_contract(store, party, data) == contract
    linked, warnings = link_change(store, document=add_doc(store), extraction=data, party=party)
    assert linked == contract and warnings == []
    assert store.get_contract(contract.id) == contract
    assert store.list_activity()[0].kind == "contract.change"


def test_unrelated_letters_are_not_linked_to_contracts(store: Store) -> None:
    party = store.add_party(name="Muster Energie")
    store.add_contract(name="Power", category="energy", party_id=party.id)
    assert link_change(
        store, document=add_doc(store), extraction=extraction(kind="invoice"), party=party
    ) == (None, [])
