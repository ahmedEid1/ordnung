"""The GiroCode payload (EPC069-12 v3.1): the standard's worked examples byte for byte, every
refusal, and properties over generated transfers (a parser in this file reads payloads back)."""

from __future__ import annotations

import string
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures_llm import iban as make_iban
from ordnung.girocode import (
    MAX_PAYLOAD_BYTES,
    GiroCodeError,
    Transfer,
    amount_text,
    clean_text,
    compact,
    creditor_reference,
    creditor_reference_valid,
    encode_payload,
    epc_payload,
    looks_like_creditor_reference,
    remittance,
)

GERMAN_IBAN = "DE05123456000004455660"  # the sample life's landlord: valid check digits, no real account

# --------------------------------------------------------------------------------------------------
# The standard's examples (EPC069-12 v3.1, section 2.3)
# --------------------------------------------------------------------------------------------------


def test_the_version_1_example_byte_for_byte() -> None:
    payload = epc_payload(
        Transfer(
            version="001",
            bic="BHBLDEHHXXX",
            name="Franz Mustermänn",
            iban="DE71110220330123456789",
            amount="12.3",
            purpose="GDDS",
            reference="RF18539007547034",
        )
    )
    assert payload == (
        "BCD\n001\n1\nSCT\nBHBLDEHHXXX\nFranz Mustermänn\nDE71110220330123456789\nEUR12.3\nGDDS\nRF18539007547034"
    )
    # "95 characters including spaces (1) and line feeds (9), 96 byte UTF-8 code payload"
    assert len(payload) == 95 and payload.count("\n") == 9
    assert len(encode_payload(payload)) == 96


def test_the_version_2_example_byte_for_byte() -> None:
    payload = epc_payload(
        Transfer(
            charset="2",
            name="François D'Alsace S.A.",
            iban="FR1420041010050500013M02606",
            amount="12.3",
            reference="Client:Marie Louise La Lune",
        )
    )
    assert payload == (
        "BCD\n002\n2\nSCT\n\nFrançois D'Alsace S.A.\nFR1420041010050500013M02606\nEUR12.3\n\n\n"
        "Client:Marie Louise La Lune"
    )
    # "103 characters including spaces (5) and line feeds (10), 103 byte ISO 8859-1 code payload"
    assert len(payload) == 103 and payload.count("\n") == 10 and payload.count(" ") == 5
    assert len(encode_payload(payload, "2")) == 103
    assert encode_payload(payload, "2") == payload.encode("latin-1")


def test_a_bill_as_ordnung_builds_it() -> None:
    """Version 002, UTF-8, no BIC (a German account), the reference as unstructured text."""
    payload = epc_payload(
        Transfer(
            name="Wohnbau Musterstadt eG", iban=GERMAN_IBAN, amount=184.3, reference="MV-2025-0412 NK 2025"
        )
    )
    assert payload == (
        "BCD\n002\n1\nSCT\n\nWohnbau Musterstadt eG\nDE05123456000004455660\nEUR184.3\n\n\nMV-2025-0412 NK 2025"
    )
    assert encode_payload(payload) == payload.encode()


def test_trailing_empty_elements_are_dropped_and_inner_ones_kept() -> None:
    assert epc_payload(Transfer(name="A", iban=GERMAN_IBAN)) == f"BCD\n002\n1\nSCT\n\nA\n{GERMAN_IBAN}"
    assert epc_payload(Transfer(name="A", iban=GERMAN_IBAN, info="Danke")) == (
        f"BCD\n002\n1\nSCT\n\nA\n{GERMAN_IBAN}\n\n\n\n\nDanke"
    )
    assert not epc_payload(Transfer(name="A", iban=GERMAN_IBAN, amount=1)).endswith("\n")


# --------------------------------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        ("12.30", "EUR12.3"),
        (Decimal("30"), "EUR30"),
        (30.0, "EUR30"),
        (184.3, "EUR184.3"),
        (94.99, "EUR94.99"),
        ("0.01", "EUR0.01"),
        ("999999999.99", "EUR999999999.99"),
        (Decimal("1E+2"), "EUR100"),
        (1234.5, "EUR1234.5"),
    ],
)
def test_amounts_are_written_like_the_standards_examples(amount: object, text: str) -> None:
    assert amount_text(amount) == text  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("amount", "why"),
    [
        ("0", "from €0.01"),
        ("-5", "from €0.01"),
        ("0.001", "from €0.01"),
        ("1000000000", "from €0.01"),
        ("12.345", "more than two decimals"),
        (0.1 + 0.2, "more than two decimals"),
        ("NaN", "not an amount"),
        ("Infinity", "not an amount"),
        ("zwölf", "not an amount"),
        ("12,30", "not an amount"),
    ],
)
def test_amounts_out_of_range_or_with_more_decimals_are_refused(amount: object, why: str) -> None:
    with pytest.raises(GiroCodeError, match=why):
        epc_payload(Transfer(name="A", iban=GERMAN_IBAN, amount=amount))  # type: ignore[arg-type]


def test_the_iban_is_written_compact_and_must_be_well_formed() -> None:
    payload = epc_payload(Transfer(name="A", iban="de05 1234-5600.0004 4556 60"))
    assert payload.splitlines()[6] == GERMAN_IBAN
    with pytest.raises(GiroCodeError, match="check digits do not match"):
        epc_payload(Transfer(name="A", iban="DE05123456000004455661"))
    with pytest.raises(GiroCodeError, match="not a country that issues IBANs"):
        epc_payload(Transfer(name="A", iban="US12345678901234567890"))
    with pytest.raises(GiroCodeError, match="Germany IBANs have 22 characters"):
        epc_payload(Transfer(name="A", iban="DE0512345600000445566"))


def test_an_account_outside_the_eea_needs_a_bic() -> None:
    swiss = make_iban("CH", "00762011623852957")
    gb = make_iban("GB", "NWBK60161331926819")
    for account in (swiss, gb):
        with pytest.raises(GiroCodeError, match="outside the EEA, so the GiroCode would need its bank's BIC"):
            epc_payload(Transfer(name="A", iban=account))
    assert epc_payload(Transfer(name="A", iban=swiss, bic="ubsw chzh 80a")).splitlines()[4] == "UBSWCHZH80A"
    for eea in (
        make_iban("NO", "86011117947"),
        make_iban("AT", "1904300234573201"),
        make_iban("IS", "0159260076545510730339"),
    ):
        assert epc_payload(Transfer(name="A", iban=eea)).splitlines()[4] == ""


def test_bic_and_purpose_codes_are_checked() -> None:
    with pytest.raises(GiroCodeError, match="needs the bank's BIC"):
        epc_payload(Transfer(version="001", name="A", iban=GERMAN_IBAN))
    with pytest.raises(GiroCodeError, match="is not a BIC"):
        epc_payload(Transfer(name="A", iban=GERMAN_IBAN, bic="DEUT"))
    with pytest.raises(GiroCodeError, match="not a purpose code"):
        epc_payload(Transfer(name="A", iban=GERMAN_IBAN, purpose="RENTS"))
    with pytest.raises(GiroCodeError, match="Unknown GiroCode version"):
        epc_payload(Transfer(name="A", iban=GERMAN_IBAN, version="003"))  # type: ignore[arg-type]
    with pytest.raises(GiroCodeError, match="Unknown character set"):
        epc_payload(Transfer(name="A", iban=GERMAN_IBAN, charset="9"))


def test_the_name_is_required_and_at_most_70_characters() -> None:
    with pytest.raises(GiroCodeError, match="needs the name of the account holder"):
        epc_payload(Transfer(name=" \n\t ", iban=GERMAN_IBAN))
    assert epc_payload(Transfer(name="x" * 70, iban=GERMAN_IBAN)).splitlines()[5] == "x" * 70
    with pytest.raises(GiroCodeError, match="longer than the 70 characters"):
        epc_payload(Transfer(name="x" * 71, iban=GERMAN_IBAN))


def test_line_breaks_and_invisible_characters_never_shift_the_elements() -> None:
    payload = epc_payload(
        Transfer(
            name="Stadtkasse\nMusterstadt ",
            iban=GERMAN_IBAN,
            amount=30,
            reference="Kassenzeichen\r\n5126\t0184​ 5122\x00",
        )
    )
    lines = payload.split("\n")
    assert len(lines) == 11
    assert lines[5] == "Stadtkasse Musterstadt"
    assert lines[10] == "Kassenzeichen 5126 0184 5122"


def test_a_valid_rf_reference_is_structured_and_the_text_element_stays_empty() -> None:
    assert remittance("RF18 5390 0754 7034") == ("RF18539007547034", "")
    assert remittance("rf18539007547034") == ("RF18539007547034", "")
    lines = epc_payload(
        Transfer(name="A", iban=GERMAN_IBAN, amount=5, reference="RF18 5390 0754 7034")
    ).split("\n")
    assert lines[9:] == ["RF18539007547034"]


def test_an_rf_reference_with_wrong_check_digits_is_refused_not_passed_on_as_text() -> None:
    assert looks_like_creditor_reference("RF19539007547034")
    with pytest.raises(GiroCodeError, match="looks like an RF creditor reference, but its check digits"):
        epc_payload(Transfer(name="A", iban=GERMAN_IBAN, reference="RF19 5390 0754 7034"))


def test_other_references_are_unstructured_text_of_at_most_140_characters() -> None:
    assert remittance("Rechnung R-2026-0815") == ("", "Rechnung R-2026-0815")
    assert remittance("RF-2026-12") == ("", "RF-2026-12")  # not shaped like an RF reference
    assert remittance(None) == ("", "") and remittance("  ") == ("", "")
    assert remittance("x" * 140) == ("", "x" * 140)
    with pytest.raises(GiroCodeError, match="longer than the 140 characters"):
        remittance("x" * 141)


def test_the_note_to_the_payer_is_at_most_70_characters() -> None:
    with pytest.raises(GiroCodeError, match="note to the payer is longer than 70"):
        epc_payload(Transfer(name="A", iban=GERMAN_IBAN, info="x" * 71))


def test_payloads_over_331_bytes_are_refused() -> None:
    # 70 three-byte characters and a 140-character reference: well over the limit in UTF-8
    with pytest.raises(GiroCodeError, match=r"need \d+ bytes, more than the 331"):
        epc_payload(Transfer(name="€" * 70, iban=GERMAN_IBAN, amount=1, reference="y" * 140))
    fits = epc_payload(Transfer(name="x" * 70, iban=GERMAN_IBAN, amount="999999999.99", reference="y" * 140))
    assert len(encode_payload(fits)) <= MAX_PAYLOAD_BYTES


def test_text_the_declared_character_set_cannot_hold_is_refused() -> None:
    with pytest.raises(GiroCodeError, match="can't be written in the declared character set"):
        epc_payload(Transfer(charset="2", name="Zahlstelle €", iban=GERMAN_IBAN))


def test_creditor_references_from_a_body() -> None:
    assert creditor_reference("539007547034") == "RF18539007547034"
    assert creditor_reference_valid("RF18 5390 0754 7034")
    assert creditor_reference_valid("RF18000000000539007547034")
    assert not creditor_reference_valid("RF18 5390 0754 7035")
    assert not creditor_reference_valid("RF185390075470341234567890")  # longer than 25 characters
    with pytest.raises(ValueError, match="1 to 21 letters or digits"):
        creditor_reference("ÄÖÜ")


# --------------------------------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------------------------------

ELEMENT_NAMES = (
    "tag",
    "version",
    "charset",
    "id",
    "bic",
    "name",
    "iban",
    "amount",
    "purpose",
    "rf",
    "text",
    "info",
)


def parse(payload: str) -> dict[str, str]:
    """A payload read back into its twelve elements (missing trailing ones are empty)."""
    lines = payload.split("\n")
    assert len(lines) <= len(ELEMENT_NAMES)
    return dict(zip(ELEMENT_NAMES, [*lines, *[""] * (len(ELEMENT_NAMES) - len(lines))], strict=True))


free_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),  # no lone surrogates (they are not text)
    max_size=160,
)
german_iban = st.text(alphabet=string.digits, min_size=18, max_size=18).map(
    lambda bban: make_iban("DE", bban)
)
cents = st.integers(min_value=1, max_value=99_999_999_999)


@settings(max_examples=300, deadline=None)
@given(name=free_text, iban=german_iban, amount=cents, reference=st.one_of(st.none(), free_text))
def test_every_payload_reads_back_to_what_was_asked_or_is_refused(
    name: str, iban: str, amount: int, reference: str | None
) -> None:
    value = Decimal(amount) / 100
    try:
        payload = epc_payload(Transfer(name=name, iban=iban, amount=value, reference=reference))
    except GiroCodeError:
        return
    assert len(payload.encode()) <= MAX_PAYLOAD_BYTES
    assert not payload.endswith("\n")
    read = parse(payload)
    assert (read["tag"], read["version"], read["charset"], read["id"], read["bic"]) == (
        "BCD",
        "002",
        "1",
        "SCT",
        "",
    )
    assert read["name"] == clean_text(name) and 1 <= len(read["name"]) <= 70
    assert read["iban"] == iban
    assert read["amount"].startswith("EUR") and Decimal(read["amount"][3:]) == value
    assert read["purpose"] == "" and read["info"] == ""
    assert not (read["rf"] and read["text"])  # only one remittance element
    if read["rf"]:
        assert creditor_reference_valid(read["rf"]) and read["rf"] == compact(clean_text(reference or ""))
    else:
        assert read["text"] == clean_text(reference or "")


@given(text=free_text)
def test_clean_text_is_one_trimmed_line_and_idempotent(text: str) -> None:
    cleaned = clean_text(text)
    assert "\n" not in cleaned and "\r" not in cleaned and " " not in cleaned
    assert cleaned == cleaned.strip() and "  " not in cleaned
    assert clean_text(cleaned) == cleaned


@given(body=st.text(alphabet=string.ascii_uppercase + string.digits, min_size=1, max_size=21), data=st.data())
def test_rf_check_digits_catch_every_change_of_one_letter_or_digit(body: str, data: st.DataObject) -> None:
    """MOD 97-10 catches any one letter changed to another letter, or digit to another digit (a letter
    for a digit changes the number's length, which the standard's check does not promise to catch)."""
    reference = creditor_reference(body)
    assert creditor_reference_valid(reference) and looks_like_creditor_reference(reference)
    position = data.draw(st.integers(min_value=2, max_value=len(reference) - 1))
    same_kind = string.digits if reference[position].isdigit() else string.ascii_uppercase
    replacement = data.draw(st.sampled_from(same_kind).filter(lambda c: c != reference[position]))
    changed = reference[:position] + replacement + reference[position + 1 :]
    assert not creditor_reference_valid(changed)


@given(amount=cents)
def test_amount_text_round_trips(amount: int) -> None:
    value = Decimal(amount) / 100
    written = amount_text(value)
    assert Decimal(written[3:]) == value
    assert not written.endswith("0") or "." not in written
