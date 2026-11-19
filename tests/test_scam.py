"""Scam checks: IBAN checksum, look-alike names and payment mismatches."""

from __future__ import annotations

from fixtures_llm import iban
from helpers_secretary import TODAY, seed_ledger
from helpers_tables import check_rows
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
from ordnung.secretary.triggers import Ledger, run_triggers

KNOWN = iban("DE", "200200200987654321")
OTHER = iban("DE", "300300300111222333")


VALID_IBANS = [
    "DE89 3704 0044 0532 0130 00",
    "de89370400440532013000",
    "GB82 WEST 1234 5698 7654 32",
    "NL91ABNA0417164300",
]


def test_valid_ibans() -> None:
    def check(value: str) -> None:
        assert iban_valid(value)

    check_rows(VALID_IBANS, check)


INVALID_IBANS = [
    "DE89 3704 0044 0532 0130 01",  # one digit changed
    "DE98 3704 0044 0532 0130 00",  # check digits swapped
    "DE89 3704 0044 0532 0130",  # too short for Germany
    "XX",
    "",
    "DE89-3704-0044-0532-0130-0X",
]


def test_invalid_ibans() -> None:
    def check(value: str) -> None:
        assert not iban_valid(value)

    check_rows(INVALID_IBANS, check)


def test_normalize_and_format() -> None:
    assert normalize_iban(" de89 3704-0044.0532 0130 00 ") == "DE89370400440532013000"
    assert format_iban("DE89370400440532013000") == "DE89 3704 0044 0532 0130 00"


LOOK_ALIKE_NAMES = [
    ("Rundfunk-Beitragsservice – Zahlungszentrale", "Beitragsservice Musterstadt"),
    ("Rundfunkbeitragsservice", "ARD ZDF Deutschlandradio Beitragsservice"),
    ("Techniker Krankenkasse Service", "Techniker Krankenkasse"),
]


def test_look_alike_names() -> None:
    def check(a: str, b: str) -> None:
        assert names_similar(a, b) and names_similar(b, a)

    check_rows(LOOK_ALIKE_NAMES, check)


DIFFERENT_ORGANISATIONS = [
    ("Finanzamt Musterstadt", "Stadtwerke Musterstadt"),  # only the town is shared
    ("Muster Telecom", "Muster Energie"),  # a short brand prefix is not distinctive
    ("AOK Krankenkasse", "Techniker Krankenkasse"),
    ("Deutsche Bahn", "Deutsche Telekom"),
]


def test_different_organisations() -> None:
    def check(a: str, b: str) -> None:
        assert not names_similar(a, b)

    check_rows(DIFFERENT_ORGANISATIONS, check)


def test_town_of_the_person_is_ignored() -> None:
    assert names_similar("Musterstadt Wohnen", "Musterstadt Energie")
    assert not names_similar("Musterstadt Wohnen", "Musterstadt Energie", ignore=["Musterstadt"])


def payment(value: str | None, payee: str | None = None) -> PaymentDetails:
    return PaymentDetails(iban=value, payee=payee)


def test_invalid_iban_is_a_finding(store: Store) -> None:
    party = store.add_party(name="Muster Energie")
    finding = payment_mismatch(store, party, payment("DE89 3704 0044 0532 0130 01"))
    assert finding is not None and finding.kind == "invalid_iban"
    assert finding.message == (
        "The IBAN DE89 3704 0044 0532 0130 01 is not a valid account number. The check digits do not match: "
        "a character is wrong, missing or swapped. It may be misprinted, misread or fake — compare it with the "
        "letter and ask the sender before paying."
    )


INVALID_IBAN_REASONS = [
    ("HR74 1234 5678 9012 3456 7890", "Croatia IBANs have 21 characters; this one has 24."),
    ("US51 1234 5678 9012 3456 7890", "US is not a country that issues IBANs, so this is not an IBAN."),
]


def test_an_invalid_iban_names_the_real_reason(store: Store) -> None:
    """Both checksums add up: the warning must not blame the check digits for a length or country problem."""
    party = store.add_party(name="Muster Energie")

    def check(value: str, reason: str) -> None:
        finding = payment_mismatch(store, party, payment(value))
        assert finding is not None and finding.kind == "invalid_iban"
        assert reason in finding.message and "check digits" not in finding.message
        assert scam.invalid_iban_message(value) == finding.message

    check_rows(INVALID_IBAN_REASONS, check)


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


# Scam signs after "an invalid IBAN alone is a misprint": ``_scam_reasons`` drops the ``invalid_iban`` finding
# and only lists the checksum "next to other signs". ``scam.payment_mismatch`` used to return ``invalid_iban``
# *first* and never ran the look-alike / changed-IBAN / changed-payee checks for such an IBAN, so those other
# signs were never found.

VALID_ABROAD = "LT121000011101001000"  # valid checksum, not the look-alike's known DE02… account
INVALID_ABROAD = "LT717300010000000000"  # fails its checksum, equally unlike DE02…
MISREAD_KNOWN = "DE02440100460123456788"  # the known DE02 4401 0046 0123 4567 89 with its last digit misread


def _scam_letter(store: Store, ids: dict[str, str], account: str) -> None:
    """The seeded letter from "Rundfunk Beitragsservice Zahlungszentrale" (a look-alike of the
    Beitragsservice that used DE02 4401 0046 0123 4567 89) with no hidden text and no model warning."""
    store.update_document(
        ids["doc_scam"],
        hidden_text=False,
        warnings=[],
        payment={"iban": account, "payee": "Beitragsservice Zahlungszentrale"},
    )


def test_an_invalid_iban_does_not_hide_a_look_alike_sender(store: Store) -> None:
    """An invalid IBAN masked the look-alike-sender check: payment_mismatch returned 'invalid_iban'
    before comparing with the similar organisation's known account, _scam_reasons then dropped that
    finding, so the letter got a calm 'looks misprinted' Info Idea and its payment stayed 'to pay'
    instead of a scam warning."""
    ids = seed_ledger(store)
    # The control: a valid foreign IBAN from the look-alike is a scam sign.
    _scam_letter(store, ids, VALID_ABROAD)
    assert [idea.kind for idea in run_triggers(store, TODAY)["scam_warning"]] == ["scam"]

    _scam_letter(store, ids, INVALID_ABROAD)
    document = store.get_document(ids["doc_scam"])
    assert document is not None

    reasons = Ledger(store, TODAY).scam_reasons(document)
    assert any("similar name" in reason for reason in reasons), reasons
    results = run_triggers(store, TODAY)
    assert [idea.kind for idea in results["scam_warning"]] == ["scam"]
    assert results["iban_misprint"] == []


def test_a_misread_known_iban_stays_a_misprint(store: Store) -> None:
    """The other checks now run for an invalid IBAN too — but one digit off an account the sender (or
    the organisation it resembles) is known to use is that account misread, not a new account."""
    ids = seed_ledger(store)
    _scam_letter(store, ids, MISREAD_KNOWN)
    results = run_triggers(store, TODAY)
    assert results["scam_warning"] == []
    assert [idea.kind for idea in results["iban_misprint"]] == ["info"]

    party = store.get_party(ids["beitrag"])
    assert party is not None
    finding = payment_mismatch(store, party, PaymentDetails(iban=MISREAD_KNOWN))
    assert finding is not None and finding.kind == "invalid_iban"  # not "iban_changed"
