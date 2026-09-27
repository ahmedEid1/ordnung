"""Citation markers in Ask answers and the labels of the visible tool trace (SPEC §10, §14).

Answers cite the ledger with markers written right after the fact they support: ``[doc:ID]``,
``[item:ID]``, ``[contract:ID]`` and ``[party:ID]``. Models sometimes group several ids in one
bracket (``[doc:doc_a, item:itm_b]``) or spell the type out (``[document:doc_a]``); both are
understood, and :func:`strip_invalid` rewrites every marker it keeps in the canonical one-id form.

Tool labels are the past-tense chips of the Ask trace ("Searched your letters for "Kündigung"");
result summaries are the short text shown once a tool answered ("Found 4 to-dos & dates"). A label
shows the model's own words only where it searched for them (a search, a name to look up), and every
word with a digit in it or in a value the answer check reads ("Ende Januar") is shown as "…": the
trace appears before the answer check, so it never shows a date, time or amount the check reads that
a letter could have put there (ADR 0008). Date ranges of the tools'
arguments are shown as the range looked at.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel

from ordnung.assistant.channels import parse_tool_result

MARKER_TYPES: tuple[str, ...] = ("doc", "item", "contract", "party")
"""Canonical marker types, as written in answers."""

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
_PAIR = r"[a-z]+\s*:\s*[a-z]{3}_[a-z0-9]+"
_GROUP_RE = re.compile(
    rf"(?P<lead>(?<![ \t])[ \t]*)\[\s*(?P<body>{_PAIR}(?:\s*[,;]\s*{_PAIR})*)\s*\]", re.IGNORECASE
)
"""A citation marker with the spaces before it; a match starts only where a run of spaces starts, so a
long run is read once (linear time)."""
_PAIR_RE = re.compile(r"(?P<type>[a-z]+)\s*:\s*(?P<id>[a-z]{3}_[a-z0-9]+)", re.IGNORECASE)

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


# --------------------------------------------------------------------------------------------------
# tool trace labels
# --------------------------------------------------------------------------------------------------

TitleLookup = Callable[[str], str | None]

_FIXED_LABELS: dict[str, str] = {
    "list_contracts": "Looked at your contracts",
    "money_summary": "Checked your money overview",
    "get_profile": "Checked your profile",
    "today": "Checked today's date",
}
_COUNTED_RESULTS: dict[str, tuple[str, str, str]] = {
    # tool → (result key, singular noun, plural noun)
    "search": ("hits", "letter", "letters"),
    "list_items": ("items", "to-do & date", "to-dos & dates"),
    "list_contracts": ("contracts", "contract", "contracts"),
    "timeline": ("entries", "date on the timeline", "dates on the timeline"),
    "get_party": ("parties", "match", "matches"),
}
_FIXED_RESULTS: dict[str, str] = {
    "get_document": "Read the letter",
    "money_summary": "Money overview ready",
    "explain_date": "Found how the date was worked out",
    "get_profile": "Profile read",
}


def tool_name(raw: str | None) -> str:
    """The short tool name (``mcp__ordnung__search`` → ``search``)."""
    name = raw or "tool"
    return name.removeprefix(TOOL_PREFIX)


def tool_label(name: str, args: Mapping[str, Any] | None = None, title_of: TitleLookup | None = None) -> str:
    """A past-tense, human label for a tool call, e.g. ``Searched your letters for "Kündigung"``.

    ``title_of`` resolves ids to titles (``Read "Mobile contract"``); without it ids stay generic.
    """
    args = args or {}
    short = tool_name(name)
    if short in _FIXED_LABELS:
        return _FIXED_LABELS[short]
    if short == "search":
        return f'Searched your letters for "{_text(args.get("query"))}"'
    if short == "get_document":
        return _titled("Read", args.get("doc_id"), title_of, fallback="Read a letter")
    if short == "list_items":
        return _items_label(args)
    if short == "get_party":
        return f'Looked up "{_text(args.get("party_id_or_name"), title_of)}"'
    if short == "timeline":
        return f"Checked your timeline from {_day(args.get('from_date'))} to {_day(args.get('to_date'))}"
    if short == "explain_date":
        found = _titled("Checked how", args.get("item_or_contract_id"), title_of, fallback="")
        return f"{found} was worked out" if found else "Checked how a date was worked out"
    return "Used a tool"


def result_summary(name: str, text: str | None) -> str:
    """A short summary of a tool result for the trace chip, e.g. ``Found 4 to-dos & dates``."""
    short = tool_name(name)
    data = _json_object(text)
    if data is None:
        return "No result"
    if data.get("found") is False:
        return "Nothing found"
    if short == "today" and isinstance(data.get("today"), str):
        return f"Today is {data['today']}"
    if short in _COUNTED_RESULTS:
        key, singular, plural = _COUNTED_RESULTS[short]
        values = data.get(key)
        if isinstance(values, list):
            return _count(len(values), singular, plural)
    return _FIXED_RESULTS.get(short, "Done")


def _items_label(args: Mapping[str, Any]) -> str:
    status = args.get("status") if args.get("status") in _STATUSES else "open"
    scope = "your to-dos & dates" if status == "all" else f"your {status} to-dos & dates"
    start, end = args.get("from_date"), args.get("to_date")
    if start and end:
        return f"Checked {scope} from {_day(start)} to {_day(end)}"
    if start or end:
        return f"Checked {scope} {'from ' + _day(start) if start else 'until ' + _day(end)}"
    return f"Checked {scope}"


def _titled(verb: str, ref_id: Any, title_of: TitleLookup | None, *, fallback: str) -> str:
    title = title_of(ref_id) if title_of is not None and isinstance(ref_id, str) else None
    return f'{verb} "{title}"' if title else fallback


_WITH_DIGIT = re.compile(r"[^\s\"“”„]*\d[^\s\"“”„]*")
_WORD_RUN = re.compile(r"[^\s\"“”„]+")
_MAX_ARGUMENT = 500
"""How much of an argument a label reads (a label shows at most 60 characters of it)."""


def _text(value: Any, title_of: TitleLookup | None = None) -> str:
    """The model's words for a label: a record's title when they name one, else as written with every
    word that holds a digit or is part of a value the answer check reads (``Ende Januar``,
    ``mid-October``) shown as "…" — never a value the check has not read —, at most 60 characters."""
    raw = " ".join(str(value or "").split())
    title = title_of(raw) if title_of is not None and raw else None
    shown = title or _masked(raw[:_MAX_ARGUMENT])
    return shown if len(shown) <= 60 else shown[:59] + "…"


def _masked(raw: str) -> str:
    """``raw`` with each word that holds a digit or a part of a stated value (the check's own reading:
    :func:`ordnung.assistant.support.stated_values`) as "…", neighbouring ones as one."""
    from ordnung.assistant.support import stated_values  # support reads this module's markers

    values = stated_values(raw)
    if any(value.start < 0 for value in values):
        return "…"  # a value that cannot be placed: show none of the words
    hidden = bytearray(len(raw))
    for value in values:
        hidden[value.start : value.end] = b"\x01" * (value.end - value.start)
    words: list[str] = []
    for match in _WORD_RUN.finditer(raw):
        masked = hidden.find(1, *match.span()) >= 0 or _WITH_DIGIT.fullmatch(match.group())
        if not masked:
            words.append(match.group())
        elif not words or words[-1] != "…":
            words.append("…")
    return " ".join(words)


def _day(value: Any) -> str:
    """A date argument (the tool accepts only ``YYYY-MM-DD``); anything else is shown as "…"."""
    return value if isinstance(value, str) and _ISO_DAY.fullmatch(value) else "…"


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_STATUSES = frozenset({"open", "done", "dismissed", "snoozed", "missed", "all"})


def _count(n: int, singular: str, plural: str) -> str:
    if n == 0:
        return f"Found no {plural}"
    return f"Found {n} {singular if n == 1 else plural}"


def _json_object(text: str | None) -> dict[str, Any] | None:
    """The record part of a tool result (what the counts and flags of the summary come from)."""
    data = parse_tool_result(text).record
    return data if isinstance(data, dict) else None
