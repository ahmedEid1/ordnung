"""How strong a new passphrase is: the one estimator a new backup and a new sync folder share (ADR 0013,
ADR 0018).

Both are files that can sit where others may copy them for years — a backup on another drive or in a
cloud folder, a sync folder's key file at the person's sync provider — open to guessing offline. So a new
one's passphrase needs about :data:`MIN_PASSPHRASE_BITS` bits by :func:`passphrase_bits`
(:func:`ordnung.backup.passphrase_problem`, :func:`ordnung.sync.passphrase_problem`, each with its own
words), and both suggest :data:`SUGGESTED_WORDS` random made-up words (:func:`suggested_passphrase`).
The web app counts the same way (``web/src/features/settings/passphrase.ts``).
"""

from __future__ import annotations

import itertools
import math
import unicodedata

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


def passphrase_tokens(passphrase: str) -> list[str]:
    """The tokens :func:`passphrase_bits` counts: the passphrase in Unicode NFC is cut into runs of
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
    """What one case-folded token counts (:func:`passphrase_bits`)."""
    if is_run(token):
        return _per_char(token) + 1.0  # about one character, and which way it runs
    if token in COMMON_WORDS:
        return min(COMMON_WORD_BITS, len(token) * _per_char(token))
    return min(len(token) * _per_char(token), TOKEN_BITS_MAX)


def passphrase_bits(passphrase: str) -> float:
    """The estimated entropy of a passphrase, in bits — a simple estimator, with a short list.

    Each *distinct* token (:func:`passphrase_tokens`, compared case-folded) counts its length times
    :data:`LETTER_BITS` (letters) or :data:`DIGIT_BITS` (digits), at most :data:`TOKEN_BITS_MAX`: a
    token is at best a word from a large list. A token that is one character again and again, runs in
    order or walks along a keyboard row (:func:`is_run`) counts about one character; a very common word
    (:data:`COMMON_WORDS`) :data:`COMMON_WORD_BITS`; and tokens that only make such a run together ("a b c
    d …") count as that one run. So five unrelated words of three or more letters reach
    :data:`MIN_PASSPHRASE_BITS`; a repeated word, a long run of one kind, a pattern ("aaa bbb ccc", "abc
    def ghi", "qwerty asdfgh"), the months or a short sentence of common words don't. The web app counts
    the same way.
    """
    tokens = [token.casefold() for token in passphrase_tokens(passphrase)]
    joined = "".join(tokens)
    if len(tokens) > 1 and is_run(joined):
        return _per_char(joined) + 1.0
    return sum(token_bits(token) for token in dict.fromkeys(tokens))


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
