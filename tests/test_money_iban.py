"""What an IBAN says about itself (``ordnung.money.iban``): shape, registered length, the mod-97
checksum and the bank code — tested on the SWIFT registry's example IBANs and on broken ones."""

from __future__ import annotations

import pytest

from ordnung.money.iban import IBAN_COUNTRIES, checksum_ok, grouped, inspect_iban, normalize

#: The registry's example IBAN of each country with a bank code position (and what it must yield).
REGISTRY_EXAMPLES = [
    ("DE89 3704 0044 0532 0130 00", "Germany", "37040044", None, "0532013000"),
    ("AT61 1904 3002 3457 3201", "Austria", "19043", None, None),
    ("CH93 0076 2011 6238 5295 7", "Switzerland", "00762", None, None),
    ("NL91 ABNA 0417 1643 00", "Netherlands", "ABNA", None, None),
    ("GB29 NWBK 6016 1331 9268 19", "United Kingdom", "NWBK", "601613", None),
    ("FR14 2004 1010 0505 0001 3M02 606", "France", "20041", "01005", None),
    ("IT60 X054 2811 1010 0000 0123 456", "Italy", "05428", "11101", None),
    ("ES91 2100 0418 4502 0005 1332", "Spain", "2100", "0418", None),
    ("BE68 5390 0754 7034", "Belgium", "539", None, None),
]


@pytest.mark.parametrize(("text", "country", "bank", "branch", "account"), REGISTRY_EXAMPLES)
def test_registry_examples_are_valid_with_their_bank_codes(
    text: str, country: str, bank: str, branch: str | None, account: str | None
) -> None:
    check = inspect_iban(text)
    assert check.valid and check.problems == []
    assert (check.country, check.bank_code, check.branch_code, check.account_number) == (
        country,
        bank,
        branch,
        account,
    )
    assert check.length_ok is True and check.bank_label


def test_printed_noise_is_ignored_and_grouping_restores_it() -> None:
    check = inspect_iban(" de89-3704.0044 0532 0130 00 ")
    assert check.valid and check.iban == "DE89370400440532013000"
    assert grouped(check.iban) == "DE89 3704 0044 0532 0130 00"
    assert normalize("gb29 nwbk") == "GB29NWBK"


def test_a_wrong_digit_fails_the_checksum() -> None:
    check = inspect_iban("DE89 3704 0044 0532 0130 01")
    assert not check.valid and not check.checksum_ok and check.length_ok is True
    assert check.bank_code is None  # no bank code is read from an IBAN that does not add up
    assert check.problems == ["The check digits do not match: a character is wrong, missing or swapped."]


def test_a_missing_character_fails_length_and_checksum() -> None:
    check = inspect_iban("DE89 3704 0044 0532 0130 0")
    assert not check.valid and check.length_ok is False and check.length_expected == 22
    assert check.problems[0] == "Germany IBANs have 22 characters; this one has 21."


def test_every_registry_country_has_its_length() -> None:
    """The full SWIFT registry: Brazil's example is valid, lengths stay within ISO 13616's 15-34."""
    assert len(IBAN_COUNTRIES) == 89
    assert all(15 <= country.length <= 34 for country in IBAN_COUNTRIES.values())
    check = inspect_iban("BR15 0000 0000 0000 1093 2840 814P 2")  # Brazil: a valid registry example
    assert check.valid and check.country == "Brazil" and check.length_ok is True and check.bank_code is None


@pytest.mark.parametrize("text", ["ZZ22 3704 0044 0532 0130 00", "US88 3704 0044 0532 0130 00"])
def test_two_letters_that_are_no_iban_country_are_not_an_iban(text: str) -> None:
    """The checksum adds up, but neither ZZ nor the US issue IBANs: not well-formed, no country guessed."""
    check = inspect_iban(text)
    assert check.shape_ok and check.checksum_ok and not check.valid
    assert (check.country_code, check.country, check.length_ok) == (None, None, None)
    assert check.problems == [f"{text[:2]} is not a country that issues IBANs, so this is not an IBAN."]


@pytest.mark.parametrize(
    "text",
    [
        "IBAN: DE89 3704 0044 0532 0130 00",  # as German letters print it
        "iban DE89 3704 0044 0532 0130 00",
        "DE89 3704 0044 0532 0130 00\u200b",  # a zero-width space copied from a PDF
        "\ufeffDE89\u00a03704 0044\u20600532 0130 00",  # a byte-order mark, a no-break space, a word joiner
    ],
)
def test_labels_and_invisible_characters_are_ignored(text: str) -> None:
    check = inspect_iban(text)
    assert check.valid and check.iban == "DE89370400440532013000" and check.country_code == "DE"


@pytest.mark.parametrize(
    "text", ["", "12345", "DE", "DE89", "D€89370400440532013000", "DEXX370400440532013000", "X" * 40]
)
def test_things_that_are_not_ibans(text: str) -> None:
    check = inspect_iban(text)
    assert not check.valid and not check.shape_ok and not check.checksum_ok
    assert check.problems and check.problems[0].startswith("It is not shaped like an IBAN")


def test_lithuanian_scam_iban_is_well_formed() -> None:
    """The demo's scam letter pays to a real-looking Lithuanian IBAN: well-formed says nothing about safety."""
    check = inspect_iban("LT08 3999 0000 0543 9871")
    assert check.valid and check.country == "Lithuania" and check.bank_code is None


def test_table_lengths_agree_with_the_scam_checks_lengths() -> None:
    from ordnung.secretary.scam import IBAN_LENGTHS

    for code, length in IBAN_LENGTHS.items():
        assert IBAN_COUNTRIES[code].length == length, code


def test_bank_code_spans_fit_inside_their_country_length() -> None:
    for code, country in IBAN_COUNTRIES.items():
        for span in (country.bank, country.branch, country.account):
            if span is not None:
                assert 4 <= span[0] < span[1] <= country.length, code
    assert checksum_ok("DE89370400440532013000")
