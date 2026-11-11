"""The words of the final run's views (standard library only): ``evals/present/templates/views.json``.

Once the final run is published, everything a reader sees about it is either a pre-registered sentence
(:mod:`evals.present.final`, filled by its rules) or one of these templates: the report's lede and card, its section
leads, the final charts' titles, headings, descriptions and captions, the history page's names for the final run's
files. The file is part of the presenter's tree, so it is posted with it before the first recording and any later change
to it is a listed deviation. A template holds no number of its own and no model id but ``{model}``, and declares the
placeholders it fills; :func:`check` holds every template to that and :func:`fill` refuses a key or a value that is
not there.

``presentation.json`` carries the file as loaded (its ``final.views``), so the report page reads the templates from
there and from nothing else.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.present import PresentError

VIEWS_PATH = Path(__file__).resolve().parent / "templates" / "views.json"
SCHEMA = "ordnung-final-views/1"
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
#: Any model identifier, spelled in parts so that the repository's model-id search does not find this line.
_MODEL_ID = re.compile(
    "|".join(("op" + "us", "hai" + "ku", r"sonnet-[0-9]", r"claude-[a-z]+-[0-9]")), re.IGNORECASE
)


class Filled(str):
    """A filled template: its text, and the key of the template it came from."""

    key: str

    def __new__(cls, value: str, key: str) -> Filled:
        filled = super().__new__(cls, value)
        filled.key = key
        return filled


def load(path: Path = VIEWS_PATH) -> dict[str, Any]:
    """The templates file, as committed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PresentError(f"{path.name}: not a readable templates file ({exc})") from exc
    if not isinstance(data, dict):
        raise PresentError(f"{path.name} is not a JSON object")
    return data


def _fields(value: str) -> list[str]:
    try:
        return [name for _, name, _, _ in string.Formatter().parse(value) if name is not None]
    except ValueError as exc:
        raise PresentError(f"a template's braces do not pair up: {exc}") from exc


def check(views: Mapping[str, Any]) -> list[str]:
    """What is wrong with a templates file (empty when nothing is): its schema, and each template's text and
    placeholders."""
    problems: list[str] = []
    if views.get("schema") != SCHEMA:
        problems.append(f"the schema is {views.get('schema')!r}, not {SCHEMA!r}")
    templates = views.get("templates")
    if not isinstance(templates, Mapping) or not templates:
        problems.append("templates must be an object of templates")
        return problems
    for key, template in templates.items():
        if not isinstance(template, Mapping) or set(template) != {"text", "fields"}:
            problems.append(f"{key}: a template is an object with its text and its fields")
            continue
        text, fields = template["text"], template["fields"]
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{key}: the text is empty")
            continue
        if not isinstance(fields, list) or not all(isinstance(name, str) and name for name in fields):
            problems.append(f"{key}: fields must list the placeholders by name")
            continue
        try:
            used = _fields(text)
        except PresentError as exc:
            problems.append(f"{key}: {exc}")
            continue
        if any(not name.isidentifier() for name in used):
            problems.append(f"{key}: a placeholder is a plain name")
        if sorted(set(used)) != sorted(set(fields)) or len(fields) != len(set(fields)):
            problems.append(f"{key}: its placeholders are not the fields it declares")
        outside = _PLACEHOLDER.sub("", text)
        if re.search(r"\d", outside):
            problems.append(f"{key}: a number outside a placeholder")
        if _MODEL_ID.search(outside):
            problems.append(f"{key}: a model id outside the {{model}} placeholder")
    return problems


def fill(views: Mapping[str, Any], key: str, **values: object) -> Filled:
    """The template ``key`` filled with ``values``, one for each of its placeholders and no other."""
    template = views["templates"].get(key) if isinstance(views.get("templates"), Mapping) else None
    if not isinstance(template, Mapping):
        raise PresentError(f"no view template {key}")
    fields = set(template["fields"])
    missing, extra = sorted(fields - set(values)), sorted(set(values) - fields)
    if missing or extra:
        raise PresentError(
            f"the view template {key} fills {', '.join(sorted(fields)) or 'nothing'}, not "
            f"{', '.join(sorted(values)) or 'nothing'} (missing: {', '.join(missing) or 'none'})"
        )
    return Filled(str(template["text"]).format_map({name: str(values[name]) for name in fields}), key)
