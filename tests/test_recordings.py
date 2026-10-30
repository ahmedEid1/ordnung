"""Every committed recording is what a recording run should leave: answered by the model its folder names, with
real usage, and no tool call in it that failed. Recordings are replayed by key, and the key holds the model the
request asked for, never the one that answered (``ordnung.llm.runtime.request_key``): a run with
``ORDNUNG_CLAUDE_MODEL`` set, or one whose MCP server did not start, replays without a word. These checks read
the files themselves (about 1,400, in well under a second)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ordnung.llm.base import DEFAULT_MODEL

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "evals" / "recorded"
DEMO = ROOT / "src" / "ordnung" / "demo" / "fixtures"


def _recordings() -> Iterator[tuple[Path, str, dict[str, Any]]]:
    """Each recording (not a recorded model failure, not a prompts lock), the model its folder is for, and its
    content: ``evals/recorded/<model>/…``, ``evals/recorded/ask/<model>/…``; the demo's are the app's pinned
    model's."""
    for root in (BENCHMARK, DEMO):
        for path in sorted(root.rglob("*.json")):
            if path.name == "prompts.lock.json" or path.name.endswith(".failure.json"):
                continue
            parts = path.relative_to(root).parts
            model = DEFAULT_MODEL if root == DEMO else parts[1] if parts[0] == "ask" else parts[0]
            yield path, model, json.loads(path.read_text(encoding="utf-8"))


def test_every_committed_recording_was_answered_by_the_pinned_model_with_usage() -> None:
    found = list(_recordings())
    assert len(found) > 1000  # the benchmark's and the demo's
    wrong = [
        f"{path.relative_to(ROOT)}: {data['response'].get('model')!r}, not {model!r}"
        for path, model, data in found
        if data["response"].get("model") != model
    ]
    assert wrong == []
    unused = [
        str(path.relative_to(ROOT))
        for path, _, data in found
        if not (data["response"]["usage"]["output_tokens"] > 0 and data["response"]["usage"]["cost_usd"] > 0)
    ]
    assert unused == []


#: A tool's own answer to a call the model got wrong ("Error executing tool explain_date: explain_date takes an
#: item id …"): the server answered, Ask's tools tell the model how to correct the call this way, and the replay
#: gives the same text again (``mcp_server.answer_again``). Any other result that starts with "Error" is a call
#: the server did not answer: the bare "Error executing tool <name>" when it was not ready or the tool crashed,
#: or the server's own error when it could not start.
_ANSWERED_BAD_CALL = re.compile(r"^Error executing tool \S+: \S")


def _broken_setup(result: str) -> bool:
    text = result.strip()
    return text.startswith("Error") and not _ANSWERED_BAD_CALL.match(text)


def test_no_recorded_turn_holds_a_tool_error() -> None:
    """A recorded Ask turn with a tool call its server did not answer measured a broken setup, not Ask: it is
    recorded again, never committed. A call the model got wrong and the tool answered with how to correct it is
    Ask's own doing, and stays (the Ask benchmark's E2 recording: two takes of one attack were recorded before
    this distinction, and the first stands)."""
    turns = [(path, data["stream"]) for path, _, data in _recordings() if data.get("stream")]
    assert len(turns) >= 100  # the Ask benchmark's turns and the demo's answers
    failed = [
        str(path.relative_to(ROOT))
        for path, stream in turns
        for event in stream
        if event.get("type") == "tool_result" and _broken_setup(str(event.get("text") or ""))
    ]
    assert failed == []
    # the forms a broken setup leaves (E2: the tool server ran two first calls at once and both crashed)
    assert _broken_setup("Error executing tool get_profile")
    assert _broken_setup("Error: MCP server ordnung failed to start")
    assert not _broken_setup(
        "Error executing tool explain_date: explain_date takes an item id (itm_…) or a contract id (ctr_…)"
    )
