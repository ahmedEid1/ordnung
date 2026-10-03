"""Messages the API sends are plain text the web app shows as they are (UI audit R1-backend-9: onboarding
and Settings showed "Run `claude` once …" with the backticks): commands are named in typographic quotes."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ordnung.api.deps import _status_detail
from ordnung.api.routes.data import DEMO_MESSAGE
from ordnung.api.routes.documents import DEMO_UPLOAD_MESSAGE
from ordnung.api.routes.drafts import DEMO_TRANSLATE_MESSAGE
from ordnung.assistant.ask import DEMO_CHANGED, DEMO_MISS, UNEXPECTED_STOP
from ordnung.demo.tour import DEMO_UNRECORDED_MESSAGE

SRC = Path(__file__).resolve().parents[1] / "src" / "ordnung"
#: Where the texts the API sends are written (reST ``literals`` in docstrings and OpenAPI docs are fine).
MESSAGE_MODULES = [
    *sorted((SRC / "api").rglob("*.py")),
    SRC / "llm" / "claude_cli.py",
    SRC / "demo" / "tour.py",
    SRC / "assistant" / "ask.py",
    SRC / "assistant" / "citations.py",
]
MARKDOWN_CODE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def test_no_markdown_code_in_what_the_api_says() -> None:
    found = []
    for path in MESSAGE_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = _docstrings(tree)
        found += [
            f"{path.relative_to(SRC)}:{node.lineno}: {node.value[:60]}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docs
            and MARKDOWN_CODE.search(node.value)
        ]
    assert found == []


def test_commands_are_named_in_quotes() -> None:
    assert "“claude”" in _status_detail(True, False)
    assert "“ordnung serve”" in DEMO_UPLOAD_MESSAGE and "“ordnung serve”" in DEMO_TRANSLATE_MESSAGE
    assert "“ordnung demo --reset”" in DEMO_MESSAGE and "“ordnung demo --reset”" in DEMO_CHANGED
    assert "“ordnung doctor”" in UNEXPECTED_STOP
    for message in (
        DEMO_MISS,
        DEMO_CHANGED,
        UNEXPECTED_STOP,
        DEMO_UNRECORDED_MESSAGE,
        _status_detail(False, None),
    ):
        assert "`" not in message
