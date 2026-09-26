"""The two channels of an Ask tool result: Ordnung's record and the letters' text (ADR 0008).

Every result of Ordnung's MCP tools has up to two parts, rendered one after the other::

    <ordnung_record>
    {"id":"doc_…","kind":"tax_assessment","items":[{"id":"itm_…","due_date":"2026-10-21",…}]}
    </ordnung_record>
    <untrusted_document>
    {"doc_…":{"title":"…","summary":"…","text":"…"},"itm_…":{"title":"…"}}
    </untrusted_document>

**The record** is what Ordnung's code computed, what the person entered or confirmed, and what the
pipeline filed with verified evidence: ids and links, types, statuses and flags; item due dates,
times and send-by dates; contract dates from the rules engine; document dates; amounts whose
evidence was found in the letter's text layer with every digit matching, or that the person gave
(ADR 0003); totals Ordnung adds up; and text written by Ordnung's code (date receipts, rules,
notes about a contract).

**The letter text** is everything that comes from a letter's words, keyed by the id of the record it
belongs to: titles, summaries, explanations, key facts, names and addresses, quotes, warnings,
payment details, the page text — and amounts or contract terms that Ordnung could not verify (read
by AI from a photo, or not found on the page). It stays inside ``<untrusted_document>`` tags.

Both parts are compact JSON with ``<`` and ``>`` escaped (``\\u003c``, ``\\u003e``), so no text can
open or close a tag. Ask's claim check (:mod:`ordnung.assistant.support`) credits a date or amount to
a record only when it appears in that record's record part.

This module is imported by the MCP server at start-up, so it stays light (standard library only).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

RECORD_OPEN = "<ordnung_record>"
RECORD_CLOSE = "</ordnung_record>"
LETTER_OPEN = "<untrusted_document>"  # the tags ordnung.ingest.extract.wrap_untrusted writes
LETTER_CLOSE = "</untrusted_document>"
VERIFIED_GROUNDING = frozenset({"verified", "user"})
"""Evidence levels whose amounts and terms belong to the record (ADR 0003: found in the text layer
with matching digits, or confirmed by the person)."""


class LetterText:
    """Collects the letter-derived fields of one tool answer, by record id (empty values dropped)."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict[str, Any]] = {}

    def add(self, record_id: str | None, **fields: Any) -> None:
        """Add ``fields`` to the letter text of ``record_id`` (nothing without an id)."""
        if not record_id:
            return
        kept = {key: value for key, value in fields.items() if value not in (None, "", [], {})}
        if kept:
            self.by_id.setdefault(record_id, {}).update(kept)

    def collect(self, record_id: str | None, **fields: Any) -> None:
        """Add each value to a list under its key (once), for records a result shows several times."""
        if not record_id:
            return
        for key, value in fields.items():
            if value in (None, "", [], {}):
                continue
            found = self.by_id.setdefault(record_id, {}).setdefault(key, [])
            if value not in found:
                found.append(value)


@dataclass
class ToolAnswer:
    """A tool's answer: the record part and the letter text by record id."""

    record: dict[str, Any]
    letters: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """A rendered tool result read back: ``record`` is ``None`` when it has no record part."""

    record: Any | None
    letters: dict[str, Any]


def compact(value: Any, *, top: bool = True) -> Any:
    """Drop ``None``, empty strings and (below the top level) empty lists and dicts."""
    if isinstance(value, dict):
        kept = {key: compact(item, top=False) for key, item in value.items()}
        return {
            key: item
            for key, item in kept.items()
            if item is not None and item != "" and (top or item not in ([], {}))
        }
    if isinstance(value, list):
        return [compact(item, top=False) for item in value]
    return value


def channel_json(data: Any) -> str:
    """Compact JSON with ``<`` and ``>`` escaped, so its text can never form a tag."""
    text = json.dumps(compact(data), ensure_ascii=False, separators=(",", ":"), default=str)
    return text.replace("<", "\\u003c").replace(">", "\\u003e")


def render_tool_result(answer: ToolAnswer) -> str:
    """The text the model reads: the record part, then the letter text (when there is any)."""
    parts = [f"{RECORD_OPEN}\n{channel_json(answer.record)}\n{RECORD_CLOSE}"]
    letters = compact(answer.letters)
    if letters:
        parts.append(f"{LETTER_OPEN}\n{channel_json(letters)}\n{LETTER_CLOSE}")
    return "\n".join(parts)


def parse_tool_result(text: str | None) -> ToolResult:
    """Read a rendered tool result back (anything else has no record part and no letter text)."""
    stripped = (text or "").strip()
    if not stripped.startswith(RECORD_OPEN):
        return ToolResult(None, {})
    end = stripped.find(RECORD_CLOSE)
    if end < 0:
        return ToolResult(None, {})
    record = _json(stripped[len(RECORD_OPEN) : end])
    rest = stripped[end + len(RECORD_CLOSE) :].strip()
    letters: Any = {}
    if rest.startswith(LETTER_OPEN) and rest.endswith(LETTER_CLOSE):
        letters = _json(rest[len(LETTER_OPEN) : -len(LETTER_CLOSE)])
    return ToolResult(record, letters if isinstance(letters, dict) else {})


def _json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except ValueError:
        return None


def is_verified(grounding: str | None) -> bool:
    """Whether evidence at this level puts its amount or terms into the record."""
    return grounding in VERIFIED_GROUNDING


_LANGUAGE_CODE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?(?:/[a-z]{2,3}(?:-[A-Za-z]{2,4})?)*")
_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


def language_code(value: str | None) -> str | None:
    """``value`` when it is a language code (``de``, ``en-GB``, ``de/en``); a letter's reading can hold
    any text."""
    return value if value is not None and _LANGUAGE_CODE.fullmatch(value) else None


def currency_code(value: str | None) -> str | None:
    """``value`` (upper-cased) when it is an ISO 4217 code such as ``EUR``, else ``None``."""
    code = (value or "").strip().upper()
    return code if _CURRENCY_CODE.fullmatch(code) else None
