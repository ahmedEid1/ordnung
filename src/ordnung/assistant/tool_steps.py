"""The labels of the visible tool trace in Ask answers and the summaries of its results (SPEC §10, §14).

Tool labels are the past-tense chips of the Ask trace ("Searched your letters for "Kündigung"");
result summaries are the short text shown once a tool answered ("Found 4 to-dos & dates"). A label
shows the model's own words only where it searched for them (a search, a name to look up), and every
word of them with a digit in it or in a value the answer check reads ("Ende Januar") is shown as "…": the
trace appears before the answer check, so it never shows a date, time or amount of the model's words the
check reads (ADR 0008). A record the model named by its id is shown by its title as the app shows it on
every list and letter page ("Read "Income tax assessment 2025""): the AI's reading of a letter, which may
hold a date the letter put there — no more than the letter's own page shows.
Date ranges of the tools' arguments are shown as the range looked at.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from ordnung.assistant.channels import parse_tool_result
from ordnung.assistant.citations import tool_name
from ordnung.rules.explain import fmt_date

# --------------------------------------------------------------------------------------------------
# tool trace labels
# --------------------------------------------------------------------------------------------------

TitleLookup = Callable[[str], str | None]

_FIXED_LABELS: dict[str, str] = {
    "list_contracts": "Looked at your contracts",
    "money_summary": "Checked your money overview",
    "get_my_numbers": "Looked up your numbers",
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
    "get_my_numbers": "Your numbers ready",
    "explain_date": "Found how the date was worked out",
    "get_profile": "Profile read",
}


def tool_label(name: str, args: Mapping[str, Any] | None = None, title_of: TitleLookup | None = None) -> str:
    """A past-tense, human label for a tool call, e.g. ``Searched your letters for “Kündigung”``, in
    the app's words: typographic quotes, dates like ``Mon 28 Sep 2026``.

    ``title_of`` resolves ids to titles (``Read “Mobile contract”``); without it ids stay generic.
    """
    args = args or {}
    short = tool_name(name)
    if short in _FIXED_LABELS:
        return _FIXED_LABELS[short]
    if short == "search":
        return f"Searched your letters for “{_text(args.get('query'))}”"
    if short == "get_document":
        return _titled("Read", args.get("doc_id"), title_of, fallback="Read a letter")
    if short == "list_items":
        return _items_label(args)
    if short == "get_party":
        return f"Looked up “{_text(args.get('party_id_or_name'), title_of)}”"
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
        return f"Today is {_day(data['today'])}" + (" (demo date)" if data.get("simulated") else "")
    if short in _COUNTED_RESULTS:
        key, singular, plural = _COUNTED_RESULTS[short]
        values = data.get(key)
        if isinstance(values, list):
            return _count(len(values), singular, plural)
    return _FIXED_RESULTS.get(short, "Done")


def _items_label(args: Mapping[str, Any]) -> str:
    status = str(args.get("status")) if args.get("status") in _STATUSES else "open"
    # a kind filter names the kind, so two filtered calls ("open deadlines", "open payments") read apart
    what = _ITEM_KINDS.get(str(args.get("kind")), "to-dos & dates")
    scope = f"your {what}" if status == "all" else f"your {_STATUS_WORDS.get(status, status)} {what}"
    start, end = args.get("from_date"), args.get("to_date")
    if start and end:
        return f"Checked {scope} from {_day(start)} to {_day(end)}"
    if start or end:
        return f"Checked {scope} {'from ' + _day(start) if start else 'until ' + _day(end)}"
    return f"Checked {scope}"


def _titled(verb: str, ref_id: Any, title_of: TitleLookup | None, *, fallback: str) -> str:
    title = title_of(ref_id) if title_of is not None and isinstance(ref_id, str) else None
    return f"{verb} “{title}”" if title else fallback


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
    """``raw`` with each word that holds a digit or a part of a stated value as "…", neighbouring ones as
    one. The values are the check's own reading of the words as shown — markup dropped, punctuation
    folded (:func:`ordnung.assistant.support.read_as_shown`, then
    :func:`~ordnung.assistant.support.stated_values`: ``Ende **Januar**``, ``mid‐January``) — mapped back
    to the words as written."""
    from ordnung.assistant.support import read_as_shown, stated_values  # support reads this module's markers

    reading = read_as_shown(raw)
    values = stated_values(reading.text)
    if any(value.start < 0 for value in values):
        return "…"  # a value that cannot be placed: show none of the words
    hidden = bytearray(len(raw))
    for value in values:
        start, end = reading.source_span(value.start, value.end)
        hidden[start:end] = b"\x01" * (end - start)
    words: list[str] = []
    for match in _WORD_RUN.finditer(raw):
        masked = hidden.find(1, *match.span()) >= 0 or _WITH_DIGIT.fullmatch(match.group())
        if not masked:
            words.append(match.group())
        elif not words or words[-1] != "…":
            words.append("…")
    return " ".join(words)


def _day(value: Any) -> str:
    """A date argument (the tool accepts only ``YYYY-MM-DD``) as the app writes dates (``Mon 28 Sep
    2026``); anything else is shown as "…"."""
    if not isinstance(value, str) or not _ISO_DAY.fullmatch(value):
        return "…"
    try:
        return fmt_date(date.fromisoformat(value))
    except ValueError:
        return "…"


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_STATUSES = frozenset({"open", "done", "dismissed", "snoozed", "missed", "all"})
#: A status in a label, as the app says it ("finished", not "done").
_STATUS_WORDS = {"done": "finished"}
#: ``list_items(kind=…)`` in a label (the kinds of :data:`ordnung.models.ItemKind`).
_ITEM_KINDS = {
    "deadline": "deadlines",
    "payment": "payments",
    "appointment": "appointments",
    "task": "tasks",
    "expiry": "expiry dates",
    "reminder": "reminders",
    "milestone": "milestones",
}


def _count(n: int, singular: str, plural: str) -> str:
    if n == 0:
        return f"Found no {plural}"
    return f"Found {n} {singular if n == 1 else plural}"


def _json_object(text: str | None) -> dict[str, Any] | None:
    """The record part of a tool result (what the counts and flags of the summary come from)."""
    data = parse_tool_result(text).record
    return data if isinstance(data, dict) else None
