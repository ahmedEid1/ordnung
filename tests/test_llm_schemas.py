"""The models Claude is given as an answer's schema (``--json-schema``): exactly these, so an edit to any other
model of ``ordnung.models`` (the API's view models, the settings, the doctor's checks) is known not to reach
Claude. ``models.py`` is one of the benchmark's digest files (``evals/conditions.py``), but only the classes here
are text a request carries."""

from __future__ import annotations

from typing import Any

import pytest
from evals import conditions
from pydantic import BaseModel

from ordnung import models
from ordnung.llm import schemas
from ordnung.llm.schemas import schema_for

#: Each schema Claude is given, its model, and every model inside it (the model itself and its ``$defs``).
GIVEN: dict[str, tuple[type[BaseModel], set[str]]] = {
    "extraction_schema": (
        models.DocumentExtraction,
        {
            "DocumentExtraction",
            "DateSpec",
            "ExtractedChange",
            "ExtractedContract",
            "ExtractedFact",
            "ExtractedItem",
            "ExtractedParty",
            "Identifier",
            "PaymentDetails",
            "Recurrence",
            "Remedy",
        },
    ),
    "transcription_schema": (models.TranscriptionOutput, {"TranscriptionOutput"}),
    "review_schema": (
        models.ReviewOutput,
        {"ReviewOutput", "ReviewSuggestion", "SuggestionAction", "SuggestionRef"},
    ),
    "brief_schema": (models.BriefOutput, {"BriefOutput"}),
    "draft_schema": (models.DraftOutput, {"DraftOutput"}),
    "draft_translation_schema": (models.DraftTranslationOutput, {"DraftTranslationOutput"}),
}
BASELINE = {"BaselineOutput", "BaselineContract", "BaselineItem", "BaselineReference"}

#: Models of ``ordnung.models`` that only the API, the settings or the doctor use: in no schema Claude is given.
NEVER_GIVEN = (
    "AppSettings",
    "ModelSettings",
    "Health",
    "ClaudeStatus",
    "DoctorCheck",
    "PictureTextStatus",
    "MyNumbers",
    "MyNumber",
    "NumbersPage",
    "PersonNumbers",
    "IdentityDocument",
    "Document",
    "LetterDetails",
)


def _inside(model: type[BaseModel]) -> set[str]:
    return {model.__name__, *model.model_json_schema().get("$defs", {})}


@pytest.mark.parametrize("name", sorted(GIVEN))
def test_the_models_claude_is_given_are_these(name: str) -> None:
    model, inside = GIVEN[name]
    given: dict[str, Any] = getattr(schemas, name)()
    assert given == schema_for(model)
    assert _inside(model) == inside


def test_the_completeness_re_ask_and_the_baselines_are_given_the_same_models() -> None:
    """The completeness re-ask is the extraction schema with more fields required; the three baselines are
    given :class:`~evals.conditions.BaselineOutput`."""
    assert schemas.completion_schema()["properties"] == schemas.extraction_schema()["properties"]
    assert conditions.baseline_schema() == schema_for(conditions.BaselineOutput)
    assert _inside(conditions.BaselineOutput) == BASELINE


def test_the_api_s_own_models_are_in_no_schema_claude_is_given() -> None:
    given = set().union(*(inside for _, inside in GIVEN.values()), BASELINE)
    for name in NEVER_GIVEN:
        assert hasattr(models, name), name
        assert name not in given, name
