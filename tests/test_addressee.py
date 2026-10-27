"""Who a letter is addressed to (``ordnung.secretary.addressee``): the written policy for when the reading's
addressee is someone else than the profile's person, and the name the letter's page shows."""

from __future__ import annotations

import pytest

from ordnung.models import Direction, Document, DocumentExtraction
from ordnung.secretary.addressee import addressed_to, is_the_person, names_alone, names_others, shown_name

SAM = "Sam Rivera"


def _letter(direction: Direction = "incoming") -> Document:
    return Document(
        id="doc_1",
        sha256="0" * 64,
        filename="letter.pdf",
        mime="application/pdf",
        direction=direction,
        created_at="2026-09-28T08:00:00Z",
        updated_at="2026-09-28T08:00:00Z",
    )


def _reading(recipient_name: str | None) -> DocumentExtraction:
    return DocumentExtraction(
        kind="other", title="A letter", summary="", explanation="", recipient_name=recipient_name
    )


@pytest.mark.parametrize(
    "addressee",
    [
        "Sam Rivera",
        "Herrn Dr. Sam Rivera",
        "Rivera, Sam",
        "S. Rivera",
        "SAM RIVERA",
        "Herrn Rivera",  # a surname alone: could be the person, so nothing is said (a known miss for a spouse)
        "Sam Peter Rivera",  # the profile's name within the addressee's
        "Sam Rivera c/o Alex Rivera",  # who it is for comes before "c/o", where it goes after
        "An Herrn Sam Rivera",
        "z. Hd. Sam Rivera",
        "Mr Sam Rivera",
    ],
)
def test_the_person_themselves_is_never_named(addressee: str) -> None:
    assert is_the_person(addressee, SAM)
    assert addressed_to(_letter(), _reading(addressee), SAM) is None


@pytest.mark.parametrize(
    ("addressee", "shown"),
    [
        ("Alex Rivera", "Alex Rivera"),
        ("Frau Alex Rivera", "Alex Rivera"),  # a leading courtesy word is dropped
        ("An Frau Alex Rivera", "Alex Rivera"),
        ("Dr. Alex Rivera", "Dr. Alex Rivera"),  # an academic title stays
        ("Herrn Dr. Alex Rivera", "Dr. Alex Rivera"),
        ("Sam und Alex Rivera", "Sam und Alex Rivera"),  # a household is not just the person
        ("Sam & Alex Rivera", "Sam & Alex Rivera"),
        ("Sam u. Alex Rivera", "Sam u. Alex Rivera"),
        ("Mr and Mrs Rivera", "Mr and Mrs Rivera"),
        ("Familie Rivera", "Familie Rivera"),
        ("Eheleute Rivera", "Eheleute Rivera"),
        ("Alex Rivera c/o Sam Rivera", "Alex Rivera"),
        ("Muster GmbH", "Muster GmbH"),
    ],
)
def test_someone_else_is_named_as_read(addressee: str, shown: str) -> None:
    assert not is_the_person(addressee, SAM)
    assert addressed_to(_letter(), _reading(addressee), SAM) == shown


def test_case_accents_and_punctuation_do_not_count() -> None:
    assert is_the_person("Jürgen Groß", "Juergen Gross")
    assert is_the_person("Herrn J. Groß", "Jürgen Groß")
    assert is_the_person("José Núñez", "Jose Nunez")
    assert is_the_person("Rivera-Lopez, Sam", "Sam Rivera-López")
    assert not is_the_person("Erika Mustermann", "Max Mustermann")
    # an initial stands for a word it begins, not for any word
    assert not is_the_person("U. Rivera", SAM)


@pytest.mark.parametrize(
    ("addressee", "profile_name"),
    [
        ("Ayşe Öztürk", "Ayse Ozturk"),
        ("Jürgen Müller", "Jurgen Muller"),
        ("Jurgen Muller", "Jürgen Müller"),
        ("Mueller", "Max Müller"),
        ("Herrn Ö. Öztürk", "Ömer Ozturk"),
    ],
)
def test_an_umlaut_may_be_written_as_a_plain_vowel_or_with_an_e(addressee: str, profile_name: str) -> None:
    assert is_the_person(addressee, profile_name)
    assert addressed_to(_letter(), _reading(addressee), profile_name) is None


def test_nothing_is_said_without_something_to_compare() -> None:
    letter = _letter()
    assert addressed_to(letter, _reading("Alex Rivera"), "") is None  # the profile has no name yet
    assert addressed_to(letter, _reading("Alex Rivera"), "  ") is None
    assert addressed_to(letter, _reading(None), SAM) is None  # the reading names no one
    assert addressed_to(letter, _reading("   "), SAM) is None
    assert addressed_to(letter, _reading("Herrn"), SAM) is None  # only a courtesy word
    assert addressed_to(letter, None, SAM) is None  # never read (queued, held, kept private)


@pytest.mark.parametrize("direction", ["outgoing", "note"])
def test_only_a_letter_received_has_an_addressee(direction: Direction) -> None:
    assert addressed_to(_letter(direction), _reading("Alex Rivera"), SAM) is None


def test_the_name_is_shown_on_one_short_line() -> None:
    assert shown_name("Alex\nRivera\t") == "Alex Rivera"
    assert shown_name("Frau​ Alex\x00 Rivera") == "Alex Rivera"
    long = addressed_to(_letter(), _reading("Alex " + "R" * 300), SAM)
    assert long is not None and len(long) == 120 and long.startswith("Alex RRR")


_ADDRESSEES = (
    "Sam Rivera",
    "Herrn Dr. Sam Rivera",
    "S. Rivera",
    "Sam Rivera c/o Alex Rivera",
    "Alex Rivera",
    "Frau Alex Rivera",
    "Sam und Alex Rivera",
    "Familie Rivera",
    "Alex Rivera c/o Sam Rivera",
    "Muster GmbH",
    "Herrn",
    "Jürgen Groß",
)


@pytest.mark.parametrize("addressee", _ADDRESSEES)
@pytest.mark.parametrize("name", [SAM, "Alex Rivera", "Juergen Gross", "J. Groß", "Rivera"])
def test_names_alone_is_is_the_person(addressee: str, name: str) -> None:
    """The household compares an addressee with each person's name by the same rule (ADR 0023): the public
    ``names_alone`` is step 1's comparison, unchanged."""
    assert names_alone(addressee, name) is is_the_person(addressee, name)
    assert names_others(addressee) is (
        "und" in addressee or "Familie" in addressee
    )  # "c/o" ends the name: what follows it never counts
