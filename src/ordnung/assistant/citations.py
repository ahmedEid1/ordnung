"""Citation markers in Ask answers (SPEC §10, §14); the labels of the visible tool trace are in
:mod:`ordnung.assistant.tool_steps`.

Answers cite the ledger with markers written right after the fact they support: ``[doc:ID]``,
``[item:ID]``, ``[contract:ID]`` and ``[party:ID]``. Models sometimes group several ids in one
bracket (``[doc:doc_a, item:itm_b]``) or spell the type out (``[document:doc_a]``); both are
understood, and :func:`strip_invalid` rewrites every marker it keeps in the canonical one-id form. A
record's type before an id no record can have (``[item:n1]``) is a marker too, so the check strips it.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Literal, NamedTuple

from pydantic import BaseModel

RefType = Literal["document", "item", "contract", "party"]
REF_TYPES: dict[str, RefType] = {"doc": "document", "item": "item", "contract": "contract", "party": "party"}
"""Marker type → ledger reference type (the ``SuggestionRef.type`` vocabulary used by the UI)."""

ID_PREFIXES: dict[str, str] = {"doc": "doc", "item": "itm", "contract": "ctr", "party": "pty"}
"""Marker type → id prefix of the records it may cite."""

_TYPE_ALIASES: dict[str, str] = {
    "doc": "doc",
    "document": "doc",
    "letter": "doc",
    "item": "item",
    "itm": "item",
    "todo": "item",
    "contract": "contract",
    "ctr": "contract",
    "party": "party",
    "pty": "party",
}
_RECORD_TYPE = "|".join(sorted(_TYPE_ALIASES, key=len, reverse=True))
_PAIR = rf"(?:[a-z]+\s*:\s*[a-z]{{3}}_[a-z0-9]+|(?:{_RECORD_TYPE})\s*:\s*[a-z0-9][a-z0-9_-]*)"
"""One cited id: any type before an id of a record's shape (``case:cas_…``), or a record's type before an
id of any shape (``item:n1``, a number's ref of ``get_my_numbers``): both are read, so the check can
strip them (no record has such an id), and neither stays in the answer as plain text."""
_GROUP_RE = re.compile(
    rf"(?P<lead>(?<![ \t])[ \t]*)\[\s*(?P<body>{_PAIR}(?:\s*[,;]\s*{_PAIR})*)\s*\]", re.IGNORECASE
)
"""A citation marker with the spaces before it; a match starts only where a run of spaces starts, so a
long run is read once (linear time)."""
_PAIR_RE = re.compile(r"(?P<type>[a-z]+)\s*:\s*(?P<id>[a-z0-9][a-z0-9_-]*)", re.IGNORECASE)
"""The ids of a marker's body (one the group pattern above has read as a marker)."""

TOOL_PREFIX = "mcp__ordnung__"


class Citation(NamedTuple):
    """One cited id: ``type`` (canonical marker type, or the unknown word as written), ``id`` and the
    ``span`` of the bracketed marker it appears in."""

    type: str
    id: str
    span: tuple[int, int]


class CitationRef(BaseModel):
    """A validated citation as sent to the UI with the final answer."""

    type: RefType
    id: str
    label: str


def canonical_type(word: str) -> str:
    """``document`` → ``doc``, ``itm`` → ``item`` …; unknown words are returned lower-cased."""
    lowered = word.lower()
    return _TYPE_ALIASES.get(lowered, lowered)


def is_well_formed(marker_type: str, ref_id: str) -> bool:
    """Whether a (canonical) marker type is known and ``ref_id`` has the matching id prefix."""
    prefix = ID_PREFIXES.get(marker_type)
    return prefix is not None and ref_id.split("_", 1)[0] == prefix


def parse_citations(text: str) -> list[Citation]:
    """Every cited id in ``text`` in reading order (grouped markers yield one entry per id)."""
    found: list[Citation] = []
    for group in _GROUP_RE.finditer(text):
        span = (group.start("lead") + len(group.group("lead")), group.end())
        for pair in _PAIR_RE.finditer(group.group("body")):
            found.append(Citation(canonical_type(pair.group("type")), pair.group("id"), span))
    return found


def strip_invalid(text: str, valid_ids: Collection[str]) -> str:
    """``text`` without markers whose id is not in ``valid_ids`` (or whose type does not fit the id).

    Kept markers are rewritten as canonical single markers (``[doc:ID][item:ID]``); a marker that
    loses all its ids disappears together with the space before it (``fact [doc:x].`` → ``fact.``).
    """

    def rewrite(group: re.Match[str]) -> str:
        kept = [
            f"[{marker_type}:{ref_id}]"
            for marker_type, ref_id in _pairs(group.group("body"))
            if is_well_formed(marker_type, ref_id) and ref_id in valid_ids
        ]
        return group.group("lead") + "".join(dict.fromkeys(kept)) if kept else ""

    return _GROUP_RE.sub(rewrite, text)


def remove_markers(text: str) -> str:
    """``text`` with every citation marker removed (for checks that must not read ids as numbers)."""
    return _GROUP_RE.sub("", text)


def marker_spans(text: str) -> list[tuple[int, int]]:
    """Where the citation markers of ``text`` stand, each with the spaces before it (what
    :func:`remove_markers` removes)."""
    return [match.span() for match in _GROUP_RE.finditer(text)]


def _pairs(body: str) -> list[tuple[str, str]]:
    return [(canonical_type(pair.group("type")), pair.group("id")) for pair in _PAIR_RE.finditer(body)]


def tool_name(raw: str | None) -> str:
    """The short tool name (``mcp__ordnung__search`` → ``search``)."""
    name = raw or "tool"
    return name.removeprefix(TOOL_PREFIX)
