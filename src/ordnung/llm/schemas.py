"""JSON schemas for structured model outputs, derived from the Pydantic models.

The Claude CLI validates the final answer against ``--json-schema``. We inline ``$ref``s so the schema
is self-contained and strip Pydantic-only noise (titles, defaults) to keep it small.
"""

from __future__ import annotations

import copy
from functools import cache
from typing import Any

from pydantic import BaseModel

from ordnung.models import (
    BriefOutput,
    CaptureOutput,
    DocumentExtraction,
    DraftOutput,
    DraftTranslationOutput,
    ReviewOutput,
    TranscriptionOutput,
)


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            merged = {**copy.deepcopy(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
            return _inline(merged, defs)
        return {k: _inline(v, defs) for k, v in node.items() if k not in ("title", "default")}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def schema_for(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    result: dict[str, Any] = _inline(raw, defs)
    return result


@cache
def extraction_schema() -> dict[str, Any]:
    return schema_for(DocumentExtraction)


@cache
def review_schema() -> dict[str, Any]:
    return schema_for(ReviewOutput)


@cache
def brief_schema() -> dict[str, Any]:
    return schema_for(BriefOutput)


@cache
def capture_schema() -> dict[str, Any]:
    return schema_for(CaptureOutput)


@cache
def draft_schema() -> dict[str, Any]:
    return schema_for(DraftOutput)


@cache
def draft_translation_schema() -> dict[str, Any]:
    return schema_for(DraftTranslationOutput)


@cache
def transcription_schema() -> dict[str, Any]:
    return schema_for(TranscriptionOutput)
