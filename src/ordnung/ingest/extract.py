"""Extraction (SPEC § 8 stage 4): one text-mode call turns a document into a ``DocumentExtraction``.

The prompt carries the page-delimited text (visible text only — hidden text never reaches a model)
inside ``<untrusted_document>`` tags, plus context: today, region, country, the person's name and
the known parties (also document-derived, so also wrapped). The cache key holds only stable inputs —
document hash, page text sources, language, region and a simulated today — never the known parties,
which depend on ingestion order. An answer that does not validate gets one repair attempt with the
validation problems appended; a second failure raises :class:`ExtractionError` with a readable message.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ordnung.ingest.text import page_delimited
from ordnung.llm import prompts
from ordnung.llm.base import LLMRequest
from ordnung.llm.claude_cli import extract_json
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import extraction_schema
from ordnung.models import DocumentExtraction, Page, Party

LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fa": "Persian",
    "fr": "French",
    "hi": "Hindi",
    "it": "Italian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "zh": "Chinese",
}
UNTRUSTED_OPEN = "<untrusted_document>"
UNTRUSTED_CLOSE = "</untrusted_document>"
_TAG_LOOKALIKE = re.compile(r"<\s*(/?)\s*untrusted[_\s-]*document\s*>", re.IGNORECASE)
_SLOT = "\x00ordnung-slot-{}\x00"
_MAX_ERRORS = 12


class ExtractionError(RuntimeError):
    """The model's answer could not be turned into a document record (message is user-presentable)."""


@dataclass(frozen=True)
class ExtractionInput:
    """Everything the extraction request is built from."""

    doc_id: str
    sha256: str
    pages: Sequence[Page]
    today: str
    language: str
    region: str
    country: str
    person_name: str
    known_parties: Sequence[Party]
    simulated_today: str | None = None


# --------------------------------------------------------------------------------------------------
# Prompt building
# --------------------------------------------------------------------------------------------------


def wrap_untrusted(text: str) -> str:
    """Wrap document-derived text in ``<untrusted_document>`` tags.

    Look-alike tags inside the text are defused first, so a document cannot close the block early.
    """
    defused = _TAG_LOOKALIKE.sub(r"[\1untrusted document tag removed]", text)
    return f"{UNTRUSTED_OPEN}\n{defused}\n{UNTRUSTED_CLOSE}"


def unwrap_untrusted(text: str) -> str:
    """The content of one :func:`wrap_untrusted` block (``text`` itself when it isn't one)."""
    stripped = text.strip()
    if stripped.startswith(UNTRUSTED_OPEN) and stripped.endswith(UNTRUSTED_CLOSE):
        return stripped[len(UNTRUSTED_OPEN) : -len(UNTRUSTED_CLOSE)].strip("\n")
    return text


def language_name(code: str) -> str:
    """English name of an ISO 639-1 language code (the code itself if unknown)."""
    return LANGUAGE_NAMES.get(code.lower(), code)


def known_parties_text(parties: Sequence[Party]) -> str:
    """One line per known party (name and kind), sorted by name, wrapped as untrusted.

    Only names and kinds: the model needs them to name a sender consistently, while matching by
    customer, file or passport numbers happens in code (:mod:`ordnung.ingest.link`), so numbers read
    from other letters never leave the computer with this one.
    """
    if not parties:
        return "(none yet)"
    lines = [
        f"- {party.name} ({party.kind})" for party in sorted(parties, key=lambda p: (p.name.casefold(), p.id))
    ]
    return wrap_untrusted("\n".join(lines))


def prompt_pages(pages: Sequence[Page]) -> list[tuple[int, str]]:
    """``(page, text)`` of the pages that have readable text (visible text only)."""
    return [(page.page, page.text) for page in pages if page.text.strip()]


def canonical_json(value: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) for cache keys."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def extraction_cache_key(data: ExtractionInput, *, repair: bool = False) -> str:
    """Stable inputs only: document hash, page text sources, language, region, simulated today."""
    key: dict[str, Any] = {
        "doc": data.sha256,
        "pages": [[page.page, page.text_source] for page in sorted(data.pages, key=lambda p: p.page)],
        "language": data.language,
        "region": data.region,
        "today": data.simulated_today,
    }
    if repair:
        key["repair"] = True
    return canonical_json(key)


def _render(name: str, untrusted: dict[str, str], **values: object) -> tuple[str, str]:
    """Render a template, inserting document-derived values only after placeholder checks.

    Document text may contain ``{{…}}`` sequences; substituting it last keeps them literal.
    """
    slots = {key: _SLOT.format(key) for key in untrusted}
    version, body = prompts.render(name, **values, **slots)
    for key, text in untrusted.items():
        body = body.replace(slots[key], text)
    return version, body


def extraction_request(data: ExtractionInput, *, model: str) -> LLMRequest:
    """The text-mode extraction request for one document."""
    system_version, system = prompts.render("extract_system", language_name=language_name(data.language))
    text_version, document = _render(
        "extract_text", {"document": wrap_untrusted(page_delimited(prompt_pages(data.pages)))}
    )
    user_version, prompt = _render(
        "extract",
        {"mode_instructions": document, "known_parties": known_parties_text(data.known_parties)},
        today=data.today,
        region=data.region,
        country=data.country,
        person_name=data.person_name or "(not given)",
    )
    return LLMRequest(
        purpose="extract",
        prompt=prompt,
        system=system,
        schema=extraction_schema(),
        doc_ids=[data.doc_id],
        model=model,
        cache_key=extraction_cache_key(data),
        prompt_version=f"{system_version}.{user_version}.{text_version}",
    )


def repair_request(request: LLMRequest, data: ExtractionInput, errors: str) -> LLMRequest:
    """The same request with the validation problems appended (its own cache key and version)."""
    version, note = prompts.render("extract_repair", errors=errors)
    return request.model_copy(
        update={
            "prompt": f"{request.prompt}\n\n{note}",
            "cache_key": extraction_cache_key(data, repair=True),
            "prompt_version": f"{request.prompt_version}.r{version}",
        }
    )


# --------------------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------------------


def validation_problems(exc: ValidationError) -> str:
    """The validation errors as bullet lines: field path and message, never the input values."""
    lines = []
    for error in exc.errors(include_url=False, include_input=False)[:_MAX_ERRORS]:
        path = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"- {path}: {error['msg']}")
    return "\n".join(lines)


def parse_extraction(data: dict[str, Any] | None, text: str) -> DocumentExtraction:
    """Validate a model answer (structured ``data`` or JSON inside ``text``)."""
    payload = data if data is not None else extract_json(text)
    return DocumentExtraction.model_validate(payload if payload is not None else {})


async def extract_document(
    llm: LLMService, data: ExtractionInput, *, model: str, use_cache: bool = True
) -> DocumentExtraction:
    """Run the extraction call, with one repair attempt if the answer does not validate."""
    request = extraction_request(data, model=model)
    response = await llm.complete(request, use_cache=use_cache)
    try:
        return parse_extraction(response.data, response.text)
    except ValidationError as first:
        problems = validation_problems(first)
    repaired = await llm.complete(repair_request(request, data, problems), use_cache=use_cache)
    try:
        return parse_extraction(repaired.data, repaired.text)
    except ValidationError as second:
        raise ExtractionError(
            "Claude's answer for this document could not be understood, even after a second try "
            f"({len(second.errors())} problem(s), e.g. {validation_problems(second).splitlines()[0][2:]}). "
            "Try “Reprocess” later."
        ) from second
