"""Scam checks: IBAN checksum, look-alike names and payment mismatches."""

from __future__ import annotations

import pytest

from fixtures_llm import iban
from ordnung.db.store import Store
from ordnung.models import PaymentDetails
from ordnung.secretary import scam
from ordnung.secretary.scam import (
    format_iban,
    iban_valid,
    names_similar,
    normalize_iban,
    payment_history,
    payment_mismatch,
)

KNOWN = iban("DE", "200200200987654321")
OTHER = iban("DE", "300300300111222333")


@pytest.mark.parametrize(
    "value",
    [
        "DE89 3704 0044 0532 0130 00",
        "de89370400440532013000",
        "GB82 WEST 1234 5698 7654 32",
        "NL91ABNA0417164300",
    ],
)
def test_valid_ibans(value: str) -> None:
    assert iban_valid(value)


@pytest.mark.parametrize(
    "value",
    [
        "DE89 3704 0044 0532 0130 01",  # one digit changed
        "DE98 3704 0044 0532 0130 00",  # check digits swapped
        "DE89 3704 0044 0532 0130",  # too short for Germany
        "XX",
        "",
        "DE89-3704-0044-0532-0130-0X",
    ],
)
def test_invalid_ibans(value: str) -> None:
    assert not iban_valid(value)


def test_normalize_and_format() -> None:
    assert normalize_iban(" de89 3704-0044.0532 0130 00 ") == "DE89370400440532013000"
    assert format_iban("DE89370400440532013000") == "DE89 3704 0044 0532 0130 00"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Rundfunk-Beitragsservice – Zahlungszentrale", "Beitragsservice Musterstadt"),
        ("Rundfunkbeitragsservice", "ARD ZDF Deutschlandradio Beitragsservice"),
        ("Techniker Krankenkasse Service", "Techniker Krankenkasse"),
    ],
)
def test_look_alike_names(a: str, b: str) -> None:
    assert names_similar(a, b) and names_similar(b, a)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Finanzamt Musterstadt", "Stadtwerke Musterstadt"),  # only the town is shared
        ("Muster Telecom", "Muster Energie"),  # a short brand prefix is not distinctive
        ("AOK Krankenkasse", "Techniker Krankenkasse"),
        ("Deutsche Bahn", "Deutsche Telekom"),
    ],
)
def test_different_organisations(a: str, b: str) -> None:
    assert not names_similar(a, b)


def test_town_of_the_person_is_ignored() -> None:
    assert names_similar("Musterstadt Wohnen", "Musterstadt Energie")
    assert not names_similar("Musterstadt Wohnen", "Musterstadt Energie", ignore=["Musterstadt"])


def payment(value: str | None, payee: str | None = None) -> PaymentDetails:
    return PaymentDetails(iban=value, payee=payee)


def test_invalid_iban_is_a_finding(store: Store) -> None:
    party = store.add_party(name="Muster Energie")
    finding = payment_mismatch(store, party, payment("DE89 3704 0044 0532 0130 01"))
    assert finding is not None and finding.kind == "invalid_iban"
    assert "check digits" in finding.message


def test_known_iban_is_fine_and_a_new_one_is_not(store: Store) -> None:
    party = store.add_party(name="Beitragsservice Musterstadt", ibans=[KNOWN])
    assert payment_mismatch(store, party, payment(format_iban(KNOWN))) is None
    finding = payment_mismatch(store, party, payment(OTHER))
    assert finding is not None and finding.kind == "iban_changed"
    assert format_iban(OTHER) in finding.message and format_iban(KNOWN) in finding.message
    assert finding.known_ibans == (KNOWN,)
    assert finding.fingerprint == f"iban_changed|{party.id}|{OTHER}|"


def test_new_look_alike_sender_is_compared_with_the_known_one(store: Store) -> None:
    genuine = store.add_party(name="Beitragsservice Musterstadt", ibans=[KNOWN])
    fake = store.add_party(name="Rundfunk-Beitragsservice – Zahlungszentrale")
    finding = payment_mismatch(store, fake, payment(OTHER, "Rundfunk-Beitragsservice"))
    assert finding is not None and finding.kind == "similar_party_iban"
    assert finding.known_party_id == genuine.id
    assert "Beitragsservice Musterstadt" in finding.message
    assert payment_mismatch(store, fake, payment(KNOWN)) is None


def test_unrelated_new_sender_is_not_flagged(store: Store) -> None:
    store.add_party(name="Stadtwerke Musterstadt", ibans=[KNOWN])
    newcomer = store.add_party(name="Finanzamt Musterstadt")
    assert payment_mismatch(store, newcomer, payment(OTHER)) is None


def test_payee_change_without_iban(store: Store) -> None:
    party = store.add_party(name="Muster Wohnen GmbH", ibans=[KNOWN])
    earlier = store.add_document(
        sha256="b" * 64, filename="rent.pdf", mime="application/pdf", file_path="r.pdf"
    )
    store.update_document(earlier.id, party_id=party.id, payment=payment(KNOWN, "Muster Wohnen GmbH"))
    assert payment_history(store, party).payees == {"Muster Wohnen GmbH"}
    assert payment_mismatch(store, party, payment(None, "Muster Wohnen")) is None
    finding = payment_mismatch(store, party, payment(None, "Max Mustermann"))
    assert finding is not None and finding.kind == "payee_changed"


def test_suspicious_ibans_never_become_history(store: Store) -> None:
    party = store.add_party(name="Rundfunk Zahlungszentrale")
    letter = store.add_document(sha256="c" * 64, filename="x.pdf", mime="application/pdf", file_path="x.pdf")
    store.update_document(letter.id, party_id=party.id, payment=payment(OTHER, "Zahlungszentrale"))
    history = payment_history(store, party)
    assert history.ibans == set() and history.payees == set()


def test_ibans_in_text_finds_printed_ibans_with_or_without_spaces() -> None:
    text = (
        "Konto: IBAN DE89 3704 0044 0532 0130 00 BIC COBADEFFXXX\n"
        "or DE89370400440532013000 again; masked DE41 XXXX XXXX XXXX XX45 00; "
        "Lithuania LT12 1000 0111 0100 1000; nonsense DE00 1234 5678 9012 3456 78"
    )
    assert scam.ibans_in_text(text) == ["DE89370400440532013000", "LT121000011101001000"]


def test_iban_from_page_needs_the_same_country_and_a_close_match() -> None:
    page = "IBAN DE89 3704 0044 0532 0130 00"
    assert scam.iban_from_page("DE89370400440532013300", page) == "DE89370400440532013000"
    assert scam.iban_from_page("AT89370400440532013300", page) is None
    assert scam.iban_from_page("DE11222233334444555566", page) is None
    assert scam.iban_from_page("DE89370400440532013300", "") is None
