"""How strong a new passphrase is: the one estimator a new backup and a new sync folder share (ADR 0013,
ADR 0018).

Both are files that can sit where others may copy them for years — a backup on another drive or in a
cloud folder, a sync folder's key file at the person's sync provider — open to guessing offline. So a new
one's passphrase needs about :data:`MIN_PASSPHRASE_BITS` bits by :func:`passphrase_bits`
(:func:`ordnung.backup.passphrase_problem`, :func:`ordnung.sync.passphrase_problem`, each with its own
words), and both suggest :data:`SUGGESTED_WORDS` random made-up words (:func:`suggested_passphrase`).
The web app counts the same way (``web/src/features/settings/passphrase.ts``); both are held to the same
vectors (``web/src/features/settings/passphraseVectors.json``).

The estimate is the largest of these counts, so none adds to another:

* **Words** (:func:`word_bits`): each distinct word or run of digits counts at most
  :data:`TOKEN_BITS_MAX`, a run or a very common word little, symbols and case nothing. Five unrelated
  words reach :data:`MIN_PASSPHRASE_BITS`.
* **Random characters** (:func:`random_bits`), what a password manager makes: :data:`RANDOM_MIN_CHARS`
  characters or more without a space count their length × log2 of the alphabet they use — 26 lower-case
  letters, 26 upper-case, 10 digits and 33 other characters, each if used (14 letters and digits: about
  83 bits) — unless they show a pattern people make (:func:`human_pattern`); then they count nothing
  this way. The patterns: a very common word of four letters or more, also with leetspeak undone
  ("P@ssw0rd"); a year, a date (its parts apart by any character but a letter or a digit, "24_12_88",
  or by the same letter twice, "24x12x88") or five digits in a row; a run of four ("abcd", "aaaa",
  "4321", the digits alone too: "a1b2c3d4") or four along a keyboard row or column ("qwer", "1qay"),
  also typed with Shift ("!QAZ", "!@#$") or as letters standing alone ("Q!W@E#R$"); four characters
  again, or three again as typed ("Ab1!Ab1?"); or words — two of four letters or more, three of any
  length, or words of four letters or more making up 60 % of it, a word being three letters or more,
  lower case or capitalised, with a vowel or a letter outside a–z (Cyrillic, Arabic …). Letters make a
  pattern only in the case people type (lower, upper, capitalised, and caps lock's or alternating case
  undone: "pASSWORT", "PaSsWoRd"): a generator's mixed case rarely spells one. And when every letter is
  in a word ("Max#Richter#94", "Familie#8312"), the words and runs of digits count as the words' count
  counts them and only the other characters as random ones.
* **Apple's strong passwords** ("kuvGis-hihvo6-quzbyc", :func:`apple_password`): their made-up words
  look like words to both counts, so their shape counts Apple's own figure,
  :data:`APPLE_PASSWORD_BITS`.

What it can't see: words it doesn't know, written in leetspeak ("Fl0w3r-G@rd3n7") or with a few random
letters added ("Andreas!88#Xy"), read as random characters; random small letters alone, which look like
one long word, count as words; the words' count, as in 0.2.0, cuts a word in alternating case at each
capital ("lIeBlInG" is five tokens); and now and then a password manager's password spells a pattern by chance
and counts as words only (fewer than 1 in 100 of each generator's, ``tests/test_passphrase_strength.py``).
"""

from __future__ import annotations

import itertools
import math
import re
import string
import unicodedata
from collections.abc import Callable, Iterable

#: A new backup's or sync folder's passphrase needs about this many bits by :func:`passphrase_bits` …
MIN_PASSPHRASE_BITS = 70.0
#: … and setup suggests this many random words (each counts :data:`TOKEN_BITS_MAX`).
SUGGESTED_WORDS = 5
#: The most one token (a word, a run of digits) counts: a word from a list of 16,384.
TOKEN_BITS_MAX = 14.0
LETTER_BITS = math.log2(26)
DIGIT_BITS = math.log2(10)
#: What a very common word counts (one of a few hundred: :data:`COMMON_WORDS`).
COMMON_WORD_BITS = 7.0
#: Keyboard rows (QWERTY, QWERTZ, AZERTY and the digits): a token along one, either way, is a walk.
KEYBOARD_ROWS: tuple[str, ...] = (
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
    "qwertzuiop",
    "asdfghjklöä",
    "yxcvbnm",
    "azertyuiop",
    "qsdfghjklm",
    "wxcvbn",
    "1234567890",
)
#: Keyboard columns (QWERTY and QWERTZ): four along one, either way, is a walk in random characters
#: (:func:`human_pattern`; the words' count looks along the rows only).
KEYBOARD_COLUMNS: tuple[str, ...] = ("1qaz", "1qay", "2wsx", "3edc", "4rfv", "5tgb", "6yhn", "6zhn", "7ujm")
#: Very common words, case-folded (the web app reads this very text): English and German short words,
#: numbers, months, days, seasons, colours and the classic passwords. Each counts
#: :data:`COMMON_WORD_BITS`.
COMMON_WORDS_TEXT = (
    "a about after all also an and any are as at back be because but by can come could day did do even "
    "first for from get give go good had has have he her him his how i if in into is it its just know "
    "like look make me most my new no not now of on one only or other our out over people say see she so "
    "some take than that the their them then there these they think this time to too two up us use want "
    "was way we well were what when which who why will with work would year yes you your "
    "der die das und ich du er sie es wir ihr ist nicht mit dem den ein eine zu von auf für im mein dein "
    "sein ja nein "
    "zero three four five six seven eight nine ten eleven twelve twenty hundred thousand second third "
    "null eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf zwanzig hundert tausend "
    "january february march april may june july august september october november december "
    "januar februar märz mai juni juli oktober dezember "
    "monday tuesday wednesday thursday friday saturday sunday "
    "montag dienstag mittwoch donnerstag freitag samstag sonntag "
    "today tomorrow yesterday heute morgen gestern "
    "spring summer autumn fall winter frühling sommer herbst "
    "red green blue yellow black white orange purple pink brown grey gray silver gold "
    "rot grün blau gelb schwarz weiss "
    "password passwort pass letmein welcome hello hallo admin login secret geheim iloveyou love liebe "
    "dragon monkey sunshine princess football master shadow test ordnung"
)
COMMON_WORDS: frozenset[str] = frozenset(COMMON_WORDS_TEXT.split())

#: Random characters count from this many on (:func:`random_bits`), the length a new passphrase needs anyway.
RANDOM_MIN_CHARS = 12
#: The alphabet random characters count: lower-case letters, upper-case letters, digits and other
#: characters (symbols, and letters without case), each if the passphrase uses one.
LOWER_ALPHABET = 26
UPPER_ALPHABET = 26
DIGIT_ALPHABET = 10
OTHER_ALPHABET = 33
#: A very common word, a run, a keyboard walk or a repeat makes a pattern from this many characters on …
PATTERN_CHARS = 4
#: … digits in a row from this many …
DIGIT_RUN_CHARS = 5
#: … a word from this many letters …
WORD_LETTERS = 3
#: … and words make a pattern when those of :data:`PATTERN_CHARS` letters or more make up this share.
WORDS_SHARE = 0.6
#: Characters again exactly as typed make a repeat from this many on ("Ab1!Ab1?").
REPEAT_CHARS = 3
#: What Shift gives on the digit row of a US and a German keyboard, undone before looking for a keyboard
#: walk: one typed with Shift is a walk too ("!QAZ@WSX", "!@#$").
SHIFTED_KEYS: tuple[dict[str, str], ...] = (
    {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0"},
    {"!": "1", '"': "2", "§": "3", "$": "4", "%": "5", "&": "6", "/": "7", "(": "8", ")": "9", "=": "0"},
)
#: Leetspeak undone before looking for a very common word ("P@ssw0rd").
LEETSPEAK = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
#: A word has one of these (also with an accent: "ä", "é").
VOWELS = "aeiouy"
#: Apple's own figure for its strong passwords (:func:`apple_password`): "71 bits of entropy".
APPLE_PASSWORD_BITS = 71.0


def passphrase_tokens(passphrase: str) -> list[str]:
    """The tokens :func:`word_bits` counts: the passphrase in Unicode NFC is cut into runs of
    letters and runs of digits (every other character only separates them), and a run of letters is
    cut again before an upper-case letter that follows a lower-case one ("CorrectHorse" is two)."""
    tokens: list[str] = []
    current = ""
    for char in unicodedata.normalize("NFC", passphrase):
        letter, digit = char.isalpha(), char.isdecimal()
        if not (letter or digit):
            if current:
                tokens.append(current)
            current = ""
            continue
        previous = current[-1] if current else ""
        same_kind = bool(previous) and (previous.isdecimal() == digit)
        camel = letter and char.isupper() and previous.islower()
        if same_kind and not camel:
            current += char
        else:
            if current:
                tokens.append(current)
            current = char
    if current:
        tokens.append(current)
    return tokens


def _per_char(token: str) -> float:
    return DIGIT_BITS if token[0].isdecimal() else LETTER_BITS


def is_run(token: str) -> bool:
    """``token`` (case-folded, three characters or more) is one character again and again ("aaa"), runs
    in order either way ("abc", "54321") or walks along a keyboard row ("qwerty", "0987")."""
    if len(token) < 3:
        return False
    if len(set(token)) == 1:
        return True
    steps = {ord(b) - ord(a) for a, b in itertools.pairwise(token)}
    if steps in ({1}, {-1}):
        return True
    return any(token in row or token in row[::-1] for row in KEYBOARD_ROWS)


def token_bits(token: str) -> float:
    """What one case-folded token counts (:func:`word_bits`)."""
    if is_run(token):
        return _per_char(token) + 1.0  # about one character, and which way it runs
    if token in COMMON_WORDS:
        return min(COMMON_WORD_BITS, len(token) * _per_char(token))
    return min(len(token) * _per_char(token), TOKEN_BITS_MAX)


def word_bits(passphrase: str) -> float:
    """The words' count of a passphrase, in bits (:func:`passphrase_bits`) — a simple estimator, with a
    short list.

    Each *distinct* token (:func:`passphrase_tokens`, compared case-folded) counts its length times
    :data:`LETTER_BITS` (letters) or :data:`DIGIT_BITS` (digits), at most :data:`TOKEN_BITS_MAX`: a
    token is at best a word from a large list. A token that is one character again and again, runs in
    order or walks along a keyboard row (:func:`is_run`) counts about one character; a very common word
    (:data:`COMMON_WORDS`) :data:`COMMON_WORD_BITS`; and tokens that only make such a run together ("a b c
    d …") count as that one run. So five unrelated words of three or more letters reach
    :data:`MIN_PASSPHRASE_BITS`; a repeated word, a long run of one kind, a pattern ("aaa bbb ccc", "abc
    def ghi", "qwerty asdfgh"), the months or a short sentence of common words don't.
    """
    tokens = [token.casefold() for token in passphrase_tokens(passphrase)]
    joined = "".join(tokens)
    if len(tokens) > 1 and is_run(joined):
        return _per_char(joined) + 1.0
    return sum(token_bits(token) for token in dict.fromkeys(tokens))


def _pieces(lines: Iterable[str], length: int) -> tuple[str, ...]:
    """Every ``length`` characters in a row of ``lines``, either way."""
    return tuple(
        sorted(
            {
                line[at : at + length]
                for row in lines
                for line in (row, row[::-1])
                for at in range(len(line) - length + 1)
            }
        )
    )


_PATTERN_WORDS = tuple(sorted(word for word in COMMON_WORDS if len(word) >= PATTERN_CHARS))
_WALKS = _pieces((*KEYBOARD_ROWS, *KEYBOARD_COLUMNS, "abcdefghijklmnopqrstuvwxyz"), PATTERN_CHARS)
_DIGITS_IN_ORDER = _pieces(("0123456789",), PATTERN_CHARS)
#: A date in a passphrase's shape (:func:`_shape`): day, month and year apart by any character but a letter
#: or a digit ("24_12_88"), or by the same letter twice between groups of two digits ("24x12x88").
_DATE = re.compile(r"9{1,2}_9{1,2}_99|99([^9_])99\1(?:99)")
_APPLE_SHAPE = re.compile(r"[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}")


def _runs(text: str, keep: Callable[[str], bool]) -> list[str]:
    """The runs of characters of ``text`` that ``keep`` keeps."""
    runs: list[str] = []
    current = ""
    for char in text:
        if keep(char):
            current += char
            continue
        if current:
            runs.append(current)
        current = ""
    if current:
        runs.append(current)
    return runs


def _shape(text: str) -> str:
    """``text`` with each digit as "9" and each character that is neither a letter nor a digit as "_"."""
    return "".join("9" if char.isdecimal() else char if char.isalpha() else "_" for char in text)


def _upper(text: str) -> list[bool]:
    """For each letter of ``text`` that has a case, whether it is upper case."""
    return [char.isupper() for char in text if char.islower() or char.isupper()]


def _plain_case(text: str) -> bool:
    """The letters of ``text`` are lower case, upper case or capitalised, as people type a word (letters
    without case, as in Arabic, fit any)."""
    upper = _upper(text)
    return not any(upper) or all(upper) or (upper[0] and not any(upper[1:]))


def _as_typed(text: str) -> str:
    """``text`` with its letters in the case people type words in, character by character: in lower case
    when every run of letters alternates, one of them :data:`PATTERN_CHARS` letters or more ("PaSsWoRd"),
    and with each letter's case swapped when capitals are more and every run is in capitals after its
    first letter (capitals, or caps lock's "pASSWORT")."""

    def changed(char: str, to: str) -> str:
        return to if len(to) == 1 else char

    runs = [_upper(run) for run in _runs(text, str.isalpha)]
    if any(len(upper) >= PATTERN_CHARS for upper in runs) and all(
        all(a != b for a, b in itertools.pairwise(upper)) for upper in runs
    ):
        return "".join(changed(char, char.lower()) if char.isupper() else char for char in text)
    capitals = sum(map(sum, runs))
    if all(all(upper[1:]) for upper in runs) and capitals > sum(map(len, runs)) - capitals:
        return "".join(
            changed(char, char.lower())
            if char.isupper()
            else changed(char, char.upper())
            if char.islower()
            else char
            for char in text
        )
    return text


def _spelled(lowered: str, text: str, pieces: Iterable[str]) -> bool:
    """One of ``pieces`` is in ``lowered`` (``text`` in lower case, character by character) where
    ``text``'s letters are in plain case (:func:`_plain_case`)."""
    for piece in pieces:
        at = lowered.find(piece)
        while at >= 0:
            if _plain_case(text[at : at + len(piece)]):
                return True
            at = lowered.find(piece, at + 1)
    return False


def _word(part: str) -> bool:
    """``part`` (of a run of letters, cut as :func:`passphrase_tokens` cuts it) can be a word: at least
    :data:`WORD_LETTERS` letters, lower case or capitalised (letters without case fit), with a vowel or a
    letter outside a–z (the words of other scripts don't show by these vowels)."""
    upper = _upper(part)
    vowel = any(
        (base := unicodedata.normalize("NFD", char.lower())[0]) in VOWELS
        or base not in string.ascii_lowercase
        for char in part
    )
    return len(part) >= WORD_LETTERS and not any(upper[1:]) and vowel


def _words(text: str) -> tuple[list[str], bool]:
    """The words of ``text``, in the case people type (:func:`_as_typed`): the parts of each run of letters
    that is made only of words — and whether every run is."""
    found: list[str] = []
    every = True
    for run in _runs(_as_typed(text), str.isalpha):
        parts = passphrase_tokens(run)
        if all(_word(part) for part in parts):
            found.extend(parts)
        else:
            every = False
    return found, every


def _is_space(char: str) -> bool:
    return unicodedata.category(char).startswith("Z") or char in "\t\n\v\f\r"


def human_pattern(passphrase: str) -> str | None:
    """The first pattern people make that ``passphrase`` shows, as :func:`random_bits` looks for them
    (``None``: none): "a very common word", "a year or a date", "five digits in a row", "a run or a
    keyboard walk", "a repeat" or "words" (the module's description says which is which)."""
    text = unicodedata.normalize("NFC", passphrase)
    typed = _as_typed(text)
    # lower case character by character, so a piece found lies where it lies in the text
    lowered = "".join(char.lower() if len(char.lower()) == 1 else char for char in text)
    unleet = "".join(LEETSPEAK.get(char, char) for char in lowered)
    if _spelled(lowered, typed, _PATTERN_WORDS) or _spelled(unleet, typed, _PATTERN_WORDS):
        return "a very common word"
    digit_runs = _runs(text, str.isdecimal)
    years = any(run[at : at + 2] in ("19", "20") for run in digit_runs for at in range(len(run) - 3))
    if years or _DATE.search(_shape(text)):
        return "a year or a date"
    if any(len(run) >= DIGIT_RUN_CHARS for run in digit_runs):
        return "five digits in a row"
    digits = "".join(digit_runs)
    # the letters that stand alone between other characters ("Q!W@E#R$")
    letters = [
        at
        for at, char in enumerate(text)
        if char.isalpha() and not text[at - 1 : at].isalpha() and not text[at + 1 : at + 2].isalpha()
    ]
    again = any(
        len(set(lowered[at : at + PATTERN_CHARS])) == 1 and _plain_case(typed[at : at + PATTERN_CHARS])
        for at in range(len(text) - PATTERN_CHARS + 1)
    )
    walk = (
        any(
            _spelled("".join(keys.get(char, char) for char in lowered), typed, _WALKS)
            for keys in ({}, *SHIFTED_KEYS)
        )
        or _spelled("".join(lowered[at] for at in letters), "".join(typed[at] for at in letters), _WALKS)
        or any(piece in digits for piece in _DIGITS_IN_ORDER)
    )
    if again or walk:
        return "a run or a keyboard walk"
    pieces = [lowered[at : at + PATTERN_CHARS] for at in range(len(lowered) - PATTERN_CHARS + 1)]
    exact = [text[at : at + REPEAT_CHARS] for at in range(len(text) - REPEAT_CHARS + 1)]
    if len(set(pieces)) < len(pieces) or len(set(exact)) < len(exact):
        return "a repeat"
    words, _ = _words(text)
    long_words = [word for word in words if len(word) >= PATTERN_CHARS]
    if len(long_words) >= 2 or len(words) >= 3 or sum(map(len, long_words)) >= WORDS_SHARE * len(text):
        return "words"
    return None


def random_bits(passphrase: str) -> float:
    """The random characters' count of a passphrase, in bits (:func:`passphrase_bits`): its length times
    log2 of the alphabet it uses (:data:`LOWER_ALPHABET` lower-case letters, :data:`UPPER_ALPHABET`
    upper-case, :data:`DIGIT_ALPHABET` digits, :data:`OTHER_ALPHABET` other characters, each if used) —
    0 below :data:`RANDOM_MIN_CHARS` characters, with a space, or with a pattern people make
    (:func:`human_pattern`). When every letter is in a word ("Max#Richter#94"), only the other characters
    count so; the words and the runs of digits count as :func:`token_bits` counts each."""
    text = unicodedata.normalize("NFC", passphrase)
    if len(text) < RANDOM_MIN_CHARS or any(_is_space(char) for char in text) or human_pattern(text):
        return 0.0
    alphabet = (
        LOWER_ALPHABET * any(char.islower() for char in text)
        + UPPER_ALPHABET * any(char.isupper() for char in text)
        + DIGIT_ALPHABET * any(char.isdecimal() for char in text)
        + OTHER_ALPHABET * any(not (char.islower() or char.isupper() or char.isdecimal()) for char in text)
    )
    per_char = math.log2(alphabet)
    words, every = _words(text)
    if not every:
        return len(text) * per_char
    others = sum(not (char.isalpha() or char.isdecimal()) for char in text)
    return (
        sum(token_bits(word.casefold()) for word in words)
        + sum(token_bits(run) for run in _runs(text, str.isdecimal))
        + others * per_char
    )


def apple_password(passphrase: str) -> bool:
    """``passphrase`` has the shape of Apple's strong passwords ("kuvGis-hihvo6-quzbyc"): three groups of
    six joined by hyphens, each two made-up syllables (consonant, vowel, consonant), with one capital and
    one digit, at a group's first or last place."""
    if not _APPLE_SHAPE.fullmatch(passphrase):
        return False
    if sum(char.isupper() for char in passphrase) != 1 or sum(char.isdigit() for char in passphrase) != 1:
        return False
    for group in passphrase.lower().split("-"):
        for at, char in enumerate(group):
            if char.isdigit():
                if at not in (0, 5):
                    return False
            elif (char in VOWELS) != (at in (1, 4)):
                return False
    return True


def passphrase_bits(passphrase: str) -> float:
    """The estimated entropy of a passphrase, in bits: the larger of :func:`word_bits` and
    :func:`random_bits`, or :data:`APPLE_PASSWORD_BITS` for one of Apple's strong passwords
    (:func:`apple_password`) — the module's description says how each counts."""
    apple = APPLE_PASSWORD_BITS if apple_password(passphrase) else 0.0
    return max(word_bits(passphrase), random_bits(passphrase), apple)


#: Easy to say and type: consonants and vowels that can't be mistaken for one another when read aloud
#: (the web app suggests the same).
SUGGEST_CONSONANTS = "bdfgjklmnprstvz"
SUGGEST_VOWELS = "aeiou"


def suggested_passphrase() -> str:
    """A random passphrase of :data:`SUGGESTED_WORDS` made-up words like ``kirun-bodaf-sumel-tavok-perin``
    (consonant-vowel-consonant-vowel-consonant: log2(15³ · 5²) ≈ 16.4 bits each, about 82 in all), from
    the system's random numbers; a word drawn twice, or one the estimator counts less (a common word), is
    drawn again — so it always protects a new backup or sync folder."""
    import secrets

    words: list[str] = []
    while len(words) < SUGGESTED_WORDS:
        word = "".join(secrets.choice(SUGGEST_CONSONANTS if i % 2 == 0 else SUGGEST_VOWELS) for i in range(5))
        if word not in words and token_bits(word) >= TOKEN_BITS_MAX:
            words.append(word)
    return "-".join(words)
