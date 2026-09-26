"""Transcription (SPEC § 8 stage 3): pages without a text layer are read by a vision call.

One call per page (``purpose="transcribe"``) with the rendered page JPEG as an image content block
and the verbatim-transcription system prompt. The cache key is the SHA-256 of the image bytes, so
the same page image is never paid for twice. The transcript is stored as the page text with
``text_source="transcript"`` — quotes found in it are only ``model_read``, never ``verified``.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ordnung.db.store import Store
from ordnung.llm import prompts
from ordnung.llm.base import Attachment, ClaudeBadOutput, LLMRequest
from ordnung.llm.claude_cli import extract_json
from ordnung.llm.runtime import LLMService
from ordnung.llm.schemas import transcription_schema
from ordnung.models import Page, TranscriptionOutput


@dataclass(frozen=True)
class PageTranscript:
    """The outcome for one page: its text (possibly empty) and whether it was legible."""

    page: int
    text: str
    legible: bool = True


def transcription_request(image_path: Path, *, doc_id: str, model: str) -> LLMRequest:
    """The vision request for one page image (cache key: SHA-256 of the image bytes)."""
    system_version, system = prompts.render("transcribe_system")
    user_version, prompt = prompts.render("transcribe")
    return LLMRequest(
        purpose="transcribe",
        prompt=prompt,
        system=system,
        schema=transcription_schema(),
        attachments=[Attachment(path=image_path, media_type="image/jpeg")],
        doc_ids=[doc_id],
        model=model,
        cache_key=hashlib.sha256(image_path.read_bytes()).hexdigest(),
        prompt_version=f"{system_version}.{user_version}",
    )


async def transcribe_page(
    llm: LLMService, image_path: Path, *, page: int, doc_id: str, model: str, use_cache: bool = True
) -> PageTranscript:
    """Transcribe one page image; raises :class:`ClaudeBadOutput` if the answer is not a transcript."""
    request = await asyncio.to_thread(transcription_request, image_path, doc_id=doc_id, model=model)
    response = await llm.complete(request, use_cache=use_cache)
    data = response.data if response.data is not None else extract_json(response.text)
    try:
        output = TranscriptionOutput.model_validate(data)
    except ValidationError as exc:
        raise ClaudeBadOutput(f"Claude's transcription of page {page} could not be read.") from exc
    return PageTranscript(page=page, text=output.text.strip(), legible=output.legible)


def pages_to_transcribe(pages: list[Page]) -> list[Page]:
    """Pages whose text does not come from the document's own text layer."""
    return [page for page in pages if page.text_source != "text"]


async def transcribe_pages(
    llm: LLMService,
    store: Store,
    doc_id: str,
    pages: list[Page],
    *,
    model: str,
    use_cache: bool = True,
) -> list[str]:
    """Transcribe every page without a text layer (concurrently) and store the transcripts.

    Returns warnings for pages that were illegible or empty. A model error (rate limit, sign-in …)
    cancels the remaining pages and propagates.
    """
    todo = pages_to_transcribe(pages)
    if not todo:
        return []
    tasks = [
        asyncio.ensure_future(
            transcribe_page(
                llm,
                store.data_dir / page.image_path,
                page=page.page,
                doc_id=doc_id,
                model=model,
                use_cache=use_cache,
            )
        )
        for page in todo
    ]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    warnings: list[str] = []
    for result in results:
        source = "transcript" if result.text else "none"
        store.set_page_text(doc_id, result.page, result.text, source)
        if not result.text or not result.legible:
            warnings.append(f"Page {result.page} is hard to read — please check it against the paper letter.")
    return warnings
