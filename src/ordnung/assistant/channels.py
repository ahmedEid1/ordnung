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
RESULT_BUDGET = 50_000
"""Characters a rendered tool result may take. A longer one is cut by rows (:func:`render_tool_result`),
so the model and Ask's check always read the same whole result: the ``claude`` CLI would otherwise
shorten an oversized result for the model, and a copy cut anywhere else would lose its closing tags."""
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


def render_tool_result(answer: ToolAnswer, *, budget: int = RESULT_BUDGET) -> str:
    """The text the model reads: the record part, then the letter text (when there is any).

    A result longer than ``budget`` characters keeps as many rows of its longest list as fit, with
    the letter text of the records still shown, and says how many rows it left out (``truncated``).
    """
    text = _render(answer)
    key = _longest_list(answer.record) if len(text) > budget else None
    if key is None:
        return text
    rows = answer.record[key]
    fits, too_many = 0, len(rows)
    while fits + 1 < too_many:  # binary search: a few renders, each linear
        middle = (fits + too_many) // 2
        if len(_render(_cut(answer, key, middle))) <= budget:
            fits = middle
        else:
            too_many = middle
    return _render(_cut(answer, key, fits))


def _render(answer: ToolAnswer) -> str:
    parts = [f"{RECORD_OPEN}\n{channel_json(answer.record)}\n{RECORD_CLOSE}"]
    letters = compact(answer.letters)
    if letters:
        parts.append(f"{LETTER_OPEN}\n{channel_json(letters)}\n{LETTER_CLOSE}")
    return "\n".join(parts)


def _longest_list(record: dict[str, Any]) -> str | None:
    lists = [(len(value), key) for key, value in record.items() if isinstance(value, list) and value]
    return max(lists)[1] if lists else None


def _cut(answer: ToolAnswer, key: str, count: int) -> ToolAnswer:
    """``answer`` with only the first ``count`` rows of ``record[key]``, and the letter text of the
    records still shown."""
    rows = answer.record[key]
    record = {
        **answer.record,
        key: rows[:count],
        "truncated": True,
        "left_out_rows": f"{len(rows) - count} more {key} not shown: ask for fewer (a narrower date range, "
        "a kind or a status)",
    }
    shown = set(_CITABLE_ID.findall(json.dumps(record, default=str)))
    return ToolAnswer(record, {ref: text for ref, text in answer.letters.items() if ref in shown})


def parse_tool_result(text: str | None) -> ToolResult:
    """Read a rendered tool result back (anything else has no record part and no letter text).

    A result cut off before its end keeps what can be read whole: the record part's complete entries
    (and the complete rows of a list cut in the middle) and the letter text's complete records. The
    record part is always rendered first and its text escapes ``<`` and ``>``, so what stands between
    ``<ordnung_record>`` and the cut is record, never letter text.
    """
    stripped = (text or "").strip()
    if not stripped.startswith(RECORD_OPEN):
        return ToolResult(None, {})
    end = stripped.find(RECORD_CLOSE)
    if end < 0:
        return ToolResult(_salvage(stripped[len(RECORD_OPEN) :]), {})
    record = _json(stripped[len(RECORD_OPEN) : end])
    rest = stripped[end + len(RECORD_CLOSE) :].strip()
    letters: Any = {}
    if rest.startswith(LETTER_OPEN):
        body = rest[len(LETTER_OPEN) :]
        whole = body.endswith(LETTER_CLOSE)
        letters = _json(body[: -len(LETTER_CLOSE)]) if whole else _salvage(body, rows=False)
    return ToolResult(record, letters if isinstance(letters, dict) else {})


def _json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except ValueError:
        return None


_DECODER = json.JSONDecoder()


def _skip(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _salvage(text: str, *, rows: bool = True) -> dict[str, Any] | None:
    """The complete ``"key": value`` entries of a JSON object that may be cut off (``rows``: also the
    complete rows of a list cut in the middle). Linear: every character is decoded at most twice."""
    index = _skip(text, 0)
    if not text.startswith("{", index):
        return None
    found: dict[str, Any] = {}
    index += 1
    while True:
        try:
            key, index = _DECODER.raw_decode(text, _skip(text, index))
        except ValueError:
            break
        index = _skip(text, index)
        if not isinstance(key, str) or not text.startswith(":", index):
            break
        start = _skip(text, index + 1)
        try:
            value, index = _DECODER.raw_decode(text, start)
        except ValueError:
            if rows and text.startswith("[", start):
                found[key] = _rows(text, start + 1)
            break
        found[key] = value
        index = _skip(text, index)
        if not text.startswith(",", index):
            break
        index += 1
    return found


def _rows(text: str, index: int) -> list[Any]:
    """The complete elements of a JSON list cut off after ``text[index]``."""
    found: list[Any] = []
    while True:
        try:
            value, index = _DECODER.raw_decode(text, _skip(text, index))
        except ValueError:
            return found
        found.append(value)
        index = _skip(text, index)
        if not text.startswith(",", index):
            return found
        index += 1


_CITABLE_ID = re.compile(r"(?:doc|itm|ctr|pty)_[a-z0-9]+")


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
