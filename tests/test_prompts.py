"""Every prompt template is present, versioned and renders — a broken template would silently send the
model an empty request (the model then correctly refuses to invent a document)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ordnung.llm import prompts

PROMPT_DIR = Path(prompts.__file__).parent
TEMPLATES = sorted(p.stem for p in PROMPT_DIR.glob("*.md"))


def test_the_core_templates_exist() -> None:
    assert {"extract", "extract_system", "transcribe_system"} <= set(TEMPLATES)


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_is_versioned_and_substantial(name: str) -> None:
    prompts.load.cache_clear()
    version, body = prompts.load(name)
    assert re.fullmatch(r"\d+", version), f"{name}: missing '<!-- version: N -->' header"
    assert len(body.strip()) >= 40, f"{name}: template is (nearly) empty"


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_renders_with_all_placeholders(name: str) -> None:
    prompts.load.cache_clear()
    _, body = prompts.load(name)
    names = set(re.findall(r"\{\{(\w+)\}\}", body))
    _, rendered = prompts.render(name, **{key: f"<{key}>" for key in names})
    for key in names:
        assert f"<{key}>" in rendered


def test_extract_template_carries_the_document() -> None:
    prompts.load.cache_clear()
    _, body = prompts.render(
        "extract",
        today="2026-09-28",
        region="NW",
        country="DE",
        person_name="Sam",
        known_parties="(none)",
        mode_instructions="<untrusted_document>TEXT</untrusted_document>",
    )
    assert "<untrusted_document>TEXT</untrusted_document>" in body
