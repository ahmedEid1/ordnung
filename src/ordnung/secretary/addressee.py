"""Who a letter is addressed to, when that isn't the person (module policy, ADR 0007).

A letter's reading names who it is addressed to (``DocumentExtraction.recipient_name``). The letter's page
says so when that is someone else — a partner, a child, "Familie …" — and a letter written from it can then
go out in that name, only when the person chooses it (ADR 0019: suggested, never set). Nothing here changes
whose letter it is: it stays filed, reminded and counted as the person's, and nothing is stored.

1. Nothing is said for a letter that isn't one received (``direction == "incoming"``), has no stored
   reading, or whose reading names no one; nor while the profile has no name, as there is nothing to
   compare with.
2. Names are compared word by word. Case, accents (ä = ae, ß = ss) and punctuation don't count, and
   neither do the titles Dr. and Prof. The addressee's leading courtesy words (Herr, Herrn, Frau, An,
   z. Hd., Mr, Mrs, Ms, Mx, Miss) are left out. Whatever follows "c/o" is where the letter goes, not who
   it is for.
3. It is the person when every word of one name is a word of the other, where an initial matches a word
   it begins ("S. Rivera", "Herrn Rivera" and "Sam Peter Rivera" are Sam Rivera). **The exception:** an
   addressee who also names others ("und", "and", "u.", "&", "+", "Familie", "Family", "Eheleute",
   "Ehepaar") is not just the person.
4. Otherwise the addressee is shown as read, on one line of at most 120 characters, without its leading
   courtesy words ("Frau Alex Rivera" shows as "Alex Rivera"; an academic title stays). A household is
   shown as written.

Known limits: a letter for a partner addressed by surname only ("Herrn Rivera") is taken as the person's,
and a misread of the person's own name ("Sam Riviera") is shown, because it is what the reading says.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from ordnung.ingest.link import party_name
from ordnung.models import Document, DocumentExtraction

_TRANSLIT: Final = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_WORD: Final = re.compile(r"[^\W\d_]+")
#: Courtesy words in front of a name: they never name someone else.
_COURTESY: Final = frozenset(
    {"herr", "herrn", "frau", "an", "z", "hd", "zhd", "mr", "mrs", "ms", "mx", "miss"}
)
#: Academic titles: never a name, wherever they stand.
_TITLES: Final = frozenset({"dr", "prof"})
#: Words that name more than one person.
_HOUSEHOLD: Final = frozenset({"und", "and", "familie", "family", "eheleute", "ehepaar"})
_HOUSEHOLD_SIGN: Final = re.compile(r"[&+]|\S\s+u\.\s+\S", re.IGNORECASE)
_CARE_OF: Final = re.compile(r"\bc\s*/\s*o\b", re.IGNORECASE)


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold().translate(_TRANSLIT)
    return "".join(char for char in unicodedata.normalize("NFKD", folded) if not unicodedata.combining(char))


def _words(text: str) -> list[str]:
    return [word for word in _WORD.findall(_fold(text)) if word not in _TITLES]


def _for_whom(addressee: str) -> str:
    """The addressee without what follows "c/o" (where the letter goes)."""
    return _CARE_OF.split(addressee, maxsplit=1)[0]


def _without_courtesy(addressee: str) -> str:
    """The addressee without its leading courtesy words ("An Frau Alex Rivera" → "Alex Rivera")."""
    words = addressee.split()
    while words and (letters := _WORD.findall(_fold(words[0]))) and all(w in _COURTESY for w in letters):
        words.pop(0)
    return " ".join(words)


def _names_others(addressee: str) -> bool:
    return bool(_HOUSEHOLD_SIGN.search(addressee)) or any(word in _HOUSEHOLD for word in _words(addressee))


def _same_word(a: str, b: str) -> bool:
    return a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def _within(words: list[str], others: list[str]) -> bool:
    return all(any(_same_word(word, other) for other in others) for word in words)


def is_the_person(addressee: str, profile_name: str) -> bool:
    """Whether ``addressee`` (as read) names the profile's person alone (points 2 and 3). ``True`` when
    either name has no words to compare: nothing is said then."""
    for_whom = _for_whom(addressee)
    if _names_others(for_whom):
        return False
    theirs, mine = _words(_without_courtesy(for_whom)), _words(profile_name)
    if not theirs or not mine:
        return True
    return _within(theirs, mine) or _within(mine, theirs)


def shown_name(addressee: str) -> str:
    """How the letter's page names the addressee (point 4)."""
    for_whom = _for_whom(addressee)
    if _names_others(for_whom):
        return party_name(for_whom)
    return party_name(_without_courtesy(party_name(for_whom)))


def addressed_to(document: Document, extraction: DocumentExtraction | None, profile_name: str) -> str | None:
    """Who the letter is addressed to when that isn't the profile's person (``None``: it is them, or
    nothing can be said — point 1)."""
    if document.direction != "incoming" or extraction is None or not profile_name.strip():
        return None
    addressee = (extraction.recipient_name or "").strip()
    if not addressee or is_the_person(addressee, profile_name):
        return None
    return shown_name(addressee) or None
