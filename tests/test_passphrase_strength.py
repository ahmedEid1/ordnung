"""How strong a new passphrase is (``ordnung.passphrase``, ADR 0013 and 0018): a password manager's random
password with capital and small letters protects a new backup or sync folder — a seeded corpus of what four
of them generate, nearly all of each (97–99 %, measured) — while what people make up is still refused (dates with any
separator, names and years, names or words with digits and symbols, leetspeak of common words, words in
capitals, with caps lock or in alternating case, words in other scripts, keyboard walks also typed with
Shift, repeats) and whatever passed before still passes. The vectors are shared with the web app's
estimator (``web/src/features/settings/passphraseVectors.json``), which its own test holds to the same
numbers."""

from __future__ import annotations

import json
import math
import random
import string
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ordnung import backup as backups
from ordnung import passphrase, sync
from ordnung.passphrase import MIN_PASSPHRASE_BITS, passphrase_bits

VECTORS_FILE = (
    Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "settings" / "passphraseVectors.json"
)
VECTORS: dict[str, list[dict[str, Any]]] = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))

#: How many passwords of each generator the corpus holds, and how many of them must pass. Not all: without a
#: dictionary, a run of random letters that reads like a word ("bicre9Gp4S60T7") counts as one, and a few
#: percent of random passwords hold one by chance. That is the price of refusing "Andreas!88#Xy" and
#: "Schm3tt3rl1ng!" (the shares are measured, less a small margin).
SAMPLES = 2000
PASSING = {"Bitwarden": 0.97, "1Password": 0.96, "Chrome": 0.98, "Apple": 0.99}
SIXTEEN_PASSING = {
    "capital and small letters": 0.99,
    "capital and small letters and digits": 0.97,
    "capital and small letters, digits and symbols": 0.93,
}

SYMBOLS = "!#$%&()*+,-./:;<=>?@[]^_{|}~"
#: Chrome leaves out characters that look alike (l, o, I, O, 0, 1).
CHROME_LOWER = "abcdefghijkmnpqrstuvwxyz"
CHROME_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CHROME_DIGITS = "23456789"
#: Apple's 19 consonants and 6 vowels; a group is two syllables, consonant-vowel-consonant.
APPLE_CONSONANTS = "bcdfghjkmnpqrstvwxz"
APPLE_VOWELS = "aeiouy"


def _random_characters(chosen: random.Random, length: int, *sets: str) -> str:
    """``length`` characters from ``sets`` together, at least one of each — as the generators make sure."""
    while True:
        drawn = "".join(chosen.choice("".join(sets)) for _ in range(length))
        if all(any(c in characters for c in drawn) for characters in sets):
            return drawn


def bitwarden(chosen: random.Random) -> str:
    """Bitwarden's default: 14 upper- and lower-case letters and digits (about 83 bits)."""
    return _random_characters(chosen, 14, string.ascii_uppercase, string.ascii_lowercase, string.digits)


def one_password(chosen: random.Random) -> str:
    """1Password's default: 20 letters, digits and symbols (about 130 bits)."""
    return _random_characters(
        chosen, 20, string.ascii_uppercase, string.ascii_lowercase, string.digits, SYMBOLS
    )


def chrome(chosen: random.Random) -> str:
    """Chrome's (Google Password Manager's): 15 letters and digits without look-alikes (about 87 bits)."""
    return _random_characters(chosen, 15, CHROME_LOWER, CHROME_UPPER, CHROME_DIGITS)


def apple(chosen: random.Random) -> str:
    """Apple's ("kuvGis-hihvo6-quzbyc"): three groups of two made-up syllables, one digit before or after a
    hyphen or at the end, one capital (about 71 bits, by Apple's count)."""
    groups = [
        [chosen.choice(APPLE_CONSONANTS if i not in (1, 4) else APPLE_VOWELS) for i in range(6)]
        for _ in range(3)
    ]
    group, at = chosen.choice([(0, 5), (1, 0), (1, 5), (2, 0), (2, 5)])
    groups[group][at] = chosen.choice(string.digits)
    letters = [(g, i) for g in range(3) for i in range(6) if groups[g][i].isalpha()]
    group, at = chosen.choice(letters)
    groups[group][at] = groups[group][at].upper()
    return "-".join("".join(group) for group in groups)


GENERATORS: dict[str, Callable[[random.Random], str]] = {
    "Bitwarden": bitwarden,
    "1Password": one_password,
    "Chrome": chrome,
    "Apple": apple,
}


def corpus(name: str) -> list[str]:
    chosen = random.Random(f"{name} {SAMPLES}")
    return [GENERATORS[name](chosen) for _ in range(SAMPLES)]


#: What the refusal of a new backup's passphrase promises passes: 16 random characters with capital and
#: small letters (and digits, or symbols, if the generator adds them).
SIXTEEN: dict[str, tuple[str, ...]] = {
    "capital and small letters": (string.ascii_uppercase, string.ascii_lowercase),
    "capital and small letters and digits": (string.ascii_uppercase, string.ascii_lowercase, string.digits),
    "capital and small letters, digits and symbols": (
        string.ascii_uppercase,
        string.ascii_lowercase,
        string.digits,
        SYMBOLS,
    ),
}


@pytest.mark.parametrize("name", list(GENERATORS))
def test_a_password_manager_s_random_password_protects_a_new_backup_and_sync_folder(name: str) -> None:
    """Audit (0.2.0 review): the estimator counted words only — symbols nothing, case nothing, a run of
    letters one word at most — so a strong password from a password manager was refused for a new backup
    and a new sync folder. Nearly all of each generator's passwords pass now (PASSING; the rest show by
    chance a pattern people make: a word-like run of letters, a common word, a year, digits in order)."""
    passwords = corpus(name)
    refused = [p for p in passwords if passphrase_bits(p) < MIN_PASSPHRASE_BITS]
    assert len(refused) <= (1 - PASSING[name]) * SAMPLES, refused[:10]
    for password in [p for p in passwords if p not in refused][:100]:
        assert sync.passphrase_problem(password) is None, password
        assert backups.passphrase_problem(password) is None, password


@pytest.mark.parametrize("sets", list(SIXTEEN))
def test_sixteen_random_capital_and_small_letters_pass_as_the_refusal_says(sets: str) -> None:
    """The refusal of a new backup's passphrase suggests "a password manager's random password of 16
    characters or more with capital and small letters": nearly all such passwords pass (SIXTEEN_PASSING)."""
    chosen = random.Random(f"sixteen {sets}")
    passwords = [_random_characters(chosen, 16, *SIXTEEN[sets]) for _ in range(SAMPLES)]
    refused = [p for p in passwords if passphrase_bits(p) < MIN_PASSPHRASE_BITS]
    assert len(refused) <= (1 - SIXTEEN_PASSING[sets]) * SAMPLES, refused[:10]
    assert "16 characters or more with capital and small letters" in backups.WEAK_PASSPHRASE_MESSAGE


def test_random_small_letters_alone_count_as_words() -> None:
    """Audit (batch A review): 16 random small letters can't be told from a long word ("bundeskanzlerin")
    without a dictionary, so they count as one word and are refused — the refusal asks for capital and
    small letters, rather than promising that any random password of 16 characters passes."""
    chosen = random.Random("sixteen small letters")
    passwords = [_random_characters(chosen, 16, string.ascii_lowercase) for _ in range(200)]
    assert sum(passphrase.human_pattern(p) == "words" for p in passwords) >= 0.9 * len(passwords)
    assert sum(passphrase_bits(p) < MIN_PASSPHRASE_BITS for p in passwords) >= 0.95 * len(passwords)
    assert "capital and small letters" in backups.WEAK_PASSPHRASE_MESSAGE


@pytest.mark.parametrize("vector", VECTORS["weak"], ids=[v["passphrase"] for v in VECTORS["weak"]])
def test_what_people_make_up_is_still_refused(vector: dict[str, Any]) -> None:
    """Dates, names and years, names or words with digits and symbols, leetspeak of common words, words in
    capitals, caps lock or alternating case, keyboard walks also typed with Shift, repeats, a few words with
    a digit or a symbol added: none reaches the bits a new backup or sync folder needs."""
    weak = vector["passphrase"]
    assert passphrase_bits(weak) < MIN_PASSPHRASE_BITS
    assert sync.passphrase_problem(weak) is not None
    assert backups.passphrase_problem(weak) is not None


@pytest.mark.parametrize("vector", VECTORS["strong"], ids=[v["passphrase"] for v in VECTORS["strong"]])
def test_a_password_manager_s_password_is_counted_as_random_characters(vector: dict[str, Any]) -> None:
    strong = vector["passphrase"]
    assert passphrase_bits(strong) >= MIN_PASSPHRASE_BITS
    assert sync.passphrase_problem(strong) is None
    assert backups.passphrase_problem(strong) is None


@pytest.mark.parametrize(
    "vector",
    VECTORS["weak"] + VECTORS["strong"],
    ids=[v["passphrase"] for v in VECTORS["weak"] + VECTORS["strong"]],
)
def test_each_vector_counts_what_the_web_app_counts_too(vector: dict[str, Any]) -> None:
    """The web app's test holds its estimator to these same bits and patterns, so the two can't drift."""
    assert passphrase_bits(vector["passphrase"]) == pytest.approx(vector["bits"], abs=1e-6)
    assert passphrase.human_pattern(vector["passphrase"]) == vector["pattern"]


def test_random_characters_count_their_length_times_the_alphabet_they_use() -> None:
    """26 lower-case letters, 26 upper-case, 10 digits and 33 other characters, each if used."""
    assert passphrase.random_bits("kT9xVbq2MzRw7p") == pytest.approx(14 * math.log2(62))
    assert passphrase.random_bits("u3wu6tIj?&pu+Vj@vt%F") == pytest.approx(20 * math.log2(95))
    assert passphrase.random_bits("k8qmx2vxdp9t") == pytest.approx(12 * math.log2(36))
    # with leetspeak digits the letters read as a word ("ktqmxevxdp"): counted as one, never as chance
    assert passphrase.random_bits("k7qmx3vxdp9t") < 12 * math.log2(36)
    assert passphrase.random_bits("Xk9#mQ2!vR7@pL4$") == pytest.approx(16 * math.log2(95))
    # at least 12 characters, and no spaces: words with spaces between them are counted as words
    assert passphrase.random_bits("kT9xVbq2MzR") == 0
    assert passphrase.random_bits("kT9xVbq 2MzRw7p") == 0


@pytest.mark.parametrize(
    ("made_up", "pattern"),
    [
        ("k7Lovej2QxZ9", "a very common word"),
        ("k7L0vej2QxZ9", "a very common word"),  # leetspeak undone
        ("xT1985kQ9vWz", "a year or a date"),
        ("xT3.7.85kQ9v", "a year or a date"),
        ("Laura#28_05_81&", "a year or a date"),  # any separator that isn't a letter or a digit
        ("Anna24x12x88!", "a year or a date"),  # the same letter twice between two-digit groups
        ("xT73829kQ9vW", "five digits in a row"),
        ("xTqwerkQ9vW7", "a run or a keyboard walk"),
        ("xTaaaakQ9vW7", "a run or a keyboard walk"),
        ("x1T2k3Q4v9Wz", "a run or a keyboard walk"),  # the digits alone: 1234
        ("!QAZ@WSX#EDC", "a run or a keyboard walk"),  # with Shift: 1qaz
        ('!"§$%&/()=?`', "a run or a keyboard walk"),  # with Shift on a German keyboard: 1234
        ("Q!W@E#R$T%Y^", "a run or a keyboard walk"),  # the letters alone: qwerty
        ("xT9kQ2xT9kQ2", "a repeat"),
        ("Ab1!Ab1?Ab1#", "a repeat"),  # three characters again, as typed
        ("Tiger7#Horse", "words"),
        ("Anna+Ben+Leo!7", "words"),
        ("Ferienhaus!!", "words"),
        ("BUNDESKANZLERIN", "words"),  # in capitals
        ("sCHMETTERLING1!", "words"),  # with caps lock
        ("pASSWORT#88!x", "a very common word"),
        ("PaSsWoRd!2#4", "a very common word"),  # in alternating case
        ("fUsSbAlL#Xq7", "words"),
        ("ПарольМосква1", "words"),  # Cyrillic: no vowels from a-z
        ("كلمةالسرمحمد1", "words"),  # Arabic: no case
    ],
)
def test_a_pattern_people_make_takes_the_count_of_random_characters_away(made_up: str, pattern: str) -> None:
    assert passphrase.human_pattern(made_up) == pattern
    assert passphrase.random_bits(made_up) == 0


def test_words_with_digits_and_symbols_count_as_words_not_random_characters() -> None:
    """Audit (batch A review): a name or a word or two with digits and symbols ("Max#Richter#94",
    "Familie#8312") showed no pattern, so every character counted as random. When every letter is in a
    word, the words and runs of digits count as tokens and only the other characters as random ones."""
    every_character = math.log2(26 + 26 + 10 + 33)
    assert passphrase.random_bits("Max#Richter#94") == pytest.approx(
        14 + 14 + 2 * math.log2(10) + 2 * every_character
    )
    assert passphrase.random_bits("Familie#8312") == pytest.approx(14 + 4 * math.log2(10) + every_character)
    assert passphrase.random_bits("Schatzi#0815!") < MIN_PASSPHRASE_BITS
    # a letter that isn't in a word: random characters, as a password manager's
    assert passphrase.random_bits("kT9xVbq2MzRw7p") == pytest.approx(14 * math.log2(62))
    # and without letters there are no words to count
    assert passphrase.random_bits("7#3$9%1&5*2(4)8!6?0;") == pytest.approx(20 * math.log2(10 + 33))


def test_letters_count_as_a_pattern_only_in_the_case_people_type() -> None:
    """Lower case, upper case or capitalised: random letters rarely are, so a common word or a walk that a
    generator's mixed case happens to spell doesn't take its password's count away."""
    assert passphrase.human_pattern("k7Lovej2QxZ9") == "a very common word"
    assert passphrase.human_pattern("k7LOVEj2QxZ9") == "a very common word"
    assert passphrase.human_pattern("k7LoVej2QxZ9") is None
    assert passphrase.human_pattern("xTqWerkQ9vW7") is None
    assert passphrase.random_bits("k7LoVej2QxZ9") == pytest.approx(12 * math.log2(62))


def test_a_word_needs_a_vowel_and_the_shape_of_a_word() -> None:
    """Lower case or capitalised, three letters or more, a vowel: "Tiger" is a word, "Tgrkz" or "tIGer" aren't."""
    assert passphrase.human_pattern("Tiger7#Horse") == "words"
    assert passphrase.human_pattern("Tgrkz7#Hrspq") is None
    assert passphrase.human_pattern("tIGer7#hORse") is None


def test_apple_s_strong_passwords_count_apple_s_own_figure() -> None:
    """Three made-up words of two syllables each look like words, so they are known by their shape: one
    capital, one digit at a group's edge, consonant-vowel-consonant twice in each group."""
    assert passphrase.apple_password("kuvGis-hihvo6-quzbyc")
    assert passphrase_bits("kuvGis-hihvo6-quzbyc") == passphrase.APPLE_PASSWORD_BITS >= MIN_PASSPHRASE_BITS
    for not_apple in (
        "kuvgis-hihvo6-quzbyc",  # no capital
        "kuvGis-hihvoq-quzbyc",  # no digit
        "kuvGis-hih6oq-quzbyc",  # the digit inside a group
        "Garden-flower-tiger7",  # "flower" isn't two syllables
        "kuvGis-hihvo6",
        "kuvGis hihvo6 quzbyc",
    ):
        assert not passphrase.apple_password(not_apple), not_apple
        assert passphrase_bits(not_apple) < MIN_PASSPHRASE_BITS, not_apple


def test_whatever_passed_before_still_passes() -> None:
    """The estimate is the largest of the counts, never less than the words' count it was: five words, the
    suggestions (Ordnung's own and 0.1.0's) and every passphrase sync's tests accept still pass."""
    chosen = random.Random(2026)
    samples = [p for name in GENERATORS for p in corpus(name)[:200]]
    samples += [v["passphrase"] for v in VECTORS["weak"] + VECTORS["strong"]]
    samples += [sync.suggested_passphrase() for _ in range(50)]
    earlier = "abcdefghjkmnpqrstuvwxyz23456789"  # what Ordnung 0.1.0's backup dialog drew from
    samples += [
        "-".join("".join(chosen.choice(earlier) for _ in range(5)) for _ in range(4)) for _ in range(50)
    ]
    for sample in samples:
        assert passphrase_bits(sample) >= passphrase.word_bits(sample), sample
    for five in (
        "orbit velvet canyon maple thunder",
        "CorrectHorseBatteryStapleMoon",
        "aqua-blunt-clay-dove-erupt",
    ):
        assert passphrase.word_bits(five) >= MIN_PASSPHRASE_BITS
        assert sync.passphrase_problem(five) is None


ROOT = Path(__file__).resolve().parents[1]

#: Every number the docs state about the count of random characters, as ``ordnung.passphrase`` has it.
_NUMBERS: dict[str, Callable[[], object]] = {
    "min_chars": lambda: passphrase.RANDOM_MIN_CHARS,
    "lower": lambda: passphrase.LOWER_ALPHABET,
    "upper": lambda: passphrase.UPPER_ALPHABET,
    "digits": lambda: passphrase.DIGIT_ALPHABET,
    "other": lambda: passphrase.OTHER_ALPHABET,
    "pattern": lambda: passphrase.PATTERN_CHARS,
    "digit_run": lambda: passphrase.DIGIT_RUN_CHARS,
    "word": lambda: passphrase.WORD_LETTERS,
    "repeat": lambda: passphrase.REPEAT_CHARS,
    "share": lambda: round(passphrase.WORDS_SHARE * 100),
    "apple": lambda: round(passphrase.APPLE_PASSWORD_BITS),
    "fourteen": lambda: round(passphrase.random_bits("kT9xVbq2MzRw7p")),  # 14 random letters and digits
}

#: ``(document, sentence)``: each ``{name}`` is filled in from :data:`_NUMBERS`; line breaks and indents
#: read as one space.
_CLAIMS: list[tuple[str, str]] = [
    (
        "docs/SPEC.md",
        "Random characters (`random_bits`): {min_chars} characters or more without a space count their "
        "length × log2 of the alphabet they use ({lower} lower-case letters, {upper} upper-case, {digits} "
        "digits, {other} other characters, each if used)",
    ),
    ("docs/SPEC.md", "a very common word of {pattern} letters or more"),
    ("docs/SPEC.md", "{digit_run} digits in a row, {pattern} in a run or along a keyboard row or column"),
    ("docs/SPEC.md", "{pattern} characters again, {repeat} again as typed, or words ({word} letters or more"),
    ("docs/SPEC.md", "those of {pattern} or more making up {share} %"),
    ("docs/SPEC.md", "count Apple's {apple} bits"),
    ("src/ordnung/passphrase.py", "(14 letters and digits: about {fourteen} bits)"),
    ("CHANGELOG.md", "14 random letters and digits are about {fourteen} bits"),
    (
        "docs/decisions/0013-backups-and-reminders-outside-the-browser.md",
        "14 random letters and digits are about {fourteen} bits",
    ),
]


@pytest.mark.parametrize(("document", "sentence"), _CLAIMS)
def test_the_docs_state_the_estimator_s_numbers(document: str, sentence: str) -> None:
    stated = sentence.format(**{name: count() for name, count in _NUMBERS.items()})
    text = " ".join((ROOT / document).read_text(encoding="utf-8").split())
    assert stated in text
