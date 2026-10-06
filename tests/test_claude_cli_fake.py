"""``ClaudeCLIBackend`` end to end against a fake ``claude`` executable (``tests/fake_claude.py``).

The fake is put on PATH and replays stream-json transcripts in the shape Claude Code 2.1 prints them
(``tests/claude_cli_outputs/*.jsonl``; a real capture can be dropped in as it is). The tests check
what the backend sends (flags on argv, the letter only on stdin), how it reads answers and errors
(classified from the ``result`` event, not the exit code), that unreadable or oversized lines don't
break it, and that a timeout or a cancelled call leaves no process behind (the CLI's process group,
MCP servers included, is killed).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ordnung.llm import claude_cli
from ordnung.llm.base import (
    Attachment,
    ClaudeAuthError,
    ClaudeBadOutput,
    ClaudeNotInstalled,
    ClaudeRateLimited,
    ClaudeTimeout,
    LLMError,
    LLMRequest,
    StreamEvent,
)
from ordnung.llm.claude_cli import ClaudeCLIBackend

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the fake CLI is started through /bin/sh")

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
LETTER = (
    "Rechnung Nr. 4711 vom 18.09.2026\nSam Rivera, Beispielweg 5, 12345 Musterstadt\n"
    "Bitte überweisen Sie 94,99 EUR bis zum 02.10.2026 auf DE02 1203 0000 0000 2020 51."
)
SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "amount": {"type": "number"}, "due_date": {"type": "string"}},
    "required": ["title"],
}
ANSWER = {"title": "Invoice 4711", "amount": 94.99, "due_date": "2026-10-02"}


@dataclass
class FakeClaude:
    """The fake ``claude`` on PATH: :meth:`play` sets what its calls do, :attr:`calls` what it got."""

    path: Path
    scenario: Path
    log: Path

    def play(self, *calls: dict[str, Any]) -> None:
        self.scenario.write_text(json.dumps({"log": str(self.log), "calls": list(calls)}), encoding="utf-8")

    @property
    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    scenario = tmp_path / "scenario.json"
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(scenario))
    return FakeClaude(path=claude, scenario=scenario, log=tmp_path / "calls.jsonl")


@pytest.fixture
def letter(tmp_path: Path) -> LLMRequest:
    """A letter to read: the text plus a page photo and the PDF, as extraction sends them."""
    photo = tmp_path / "page-1.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF fake page photo \xff\xd9")
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% fake letter\n%%EOF\n")
    return LLMRequest(
        purpose="extract",
        prompt=LETTER,
        system="You read letters and return the dates in them.",
        schema=SCHEMA,
        attachments=[
            Attachment(path=photo, media_type="image/jpeg"),
            Attachment(path=pdf, media_type="application/pdf"),
        ],
        timeout_s=20,
    )


def _alive(pid: int) -> bool:
    """Whether ``pid`` still runs (a zombie waiting to be reaped counts as gone)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        state = proc_stat.read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return True
    return state != "Z"


async def _eventually(check: Callable[[], bool], within: float = 5.0) -> bool:
    """Poll ``check``; the event loop keeps running meanwhile, so the backend can clean up."""
    deadline = time.monotonic() + within
    while not check():
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def _gone(*pids: int) -> bool:
    return await _eventually(lambda: not any(_alive(pid) for pid in pids))


# --------------------------------------------------------------------------------------------------
# what is sent
# --------------------------------------------------------------------------------------------------


async def test_the_letter_goes_on_stdin_never_on_argv(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"transcript": "extract_structured.jsonl"})
    response = await ClaudeCLIBackend(max_retries=0).complete(letter)

    (call,) = fake.calls
    argv = call["argv"]
    for secret in ("4711", "Sam Rivera", "Beispielweg", "94,99", "DE02"):
        assert not any(secret in arg for arg in argv), secret
    assert "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--tools") + 1] == ""  # extraction may use no tool at all
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert {"-p", "--strict-mcp-config", "--no-session-persistence"} <= set(argv)
    assert argv[argv.index("--input-format") + 1] == argv[argv.index("--output-format") + 1] == "stream-json"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA
    assert "--include-partial-messages" not in argv

    (line,) = call["stdin"].splitlines()
    message = json.loads(line)
    assert message["type"] == "user" and message["message"]["role"] == "user"
    text, photo, pdf = message["message"]["content"]
    assert text == {"type": "text", "text": LETTER}
    assert photo["type"] == "image" and photo["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(photo["source"]["data"]) == letter.attachments[0].path.read_bytes()
    assert pdf["type"] == "document" and pdf["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(pdf["source"]["data"]) == letter.attachments[1].path.read_bytes()

    assert response.data == ANSWER
    assert response.text == "Done."
    assert response.model == "claude-family-x-1"  # the model that answered, from modelUsage
    assert response.backend == "claude"
    usage = response.usage
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (6, 70, 2311)
    assert (usage.cost_usd, usage.duration_ms, usage.turns) == (0.01234, 5123, 2)


async def test_an_explicit_binary_path_is_used(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"transcript": "extract_structured.jsonl"})
    backend = ClaudeCLIBackend(binary=str(fake.path), max_retries=0)
    assert backend.binary == str(fake.path)
    assert (await backend.complete(letter)).data == ANSWER


async def test_no_claude_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, letter: LLMRequest) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    with pytest.raises(ClaudeNotInstalled):
        await ClaudeCLIBackend(max_retries=0).complete(letter)


async def test_claude_installed_after_the_backend_was_made_is_found(
    fake: FakeClaude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, letter: LLMRequest
) -> None:
    """Not found when the backend was made: each call looks on PATH again, so installing Claude while
    Ordnung runs needs no restart (and no status check in between)."""
    path = os.environ["PATH"]
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    backend = ClaudeCLIBackend(max_retries=0)
    assert backend.binary is None
    with pytest.raises(ClaudeNotInstalled):
        await backend.complete(letter)
    monkeypatch.setenv("PATH", path)  # installed meanwhile
    fake.play({"transcript": "extract_structured.jsonl"})
    assert (await backend.complete(letter)).data == ANSWER
    assert backend.binary == str(fake.path)


@pytest.mark.parametrize("broken", ["not_executable", "moved"])
async def test_a_claude_that_cant_be_started_is_not_installed(
    fake: FakeClaude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, letter: LLMRequest, broken: str
) -> None:
    """ROB G3: an operating-system error starting ``claude`` (not executable, moved or uninstalled since it
    was found) is :class:`ClaudeNotInstalled` with a readable message — for a reading, Ask's stream and the
    probe behind "Run check" and ``doctor --probe`` — never a crash."""
    found = str(fake.path)
    backend, asking = ClaudeCLIBackend(max_retries=0), ClaudeCLIBackend(max_retries=0)
    assert backend.binary == asking.binary == found
    if broken == "not_executable":
        fake.path.chmod(0o644)
    else:
        fake.path.rename(tmp_path / "claude-elsewhere")
    with pytest.raises(ClaudeNotInstalled, match="could not be started"):
        await backend.complete(letter)
    assert backend.binary is None  # looked for again next time
    request = LLMRequest(purpose="ask", prompt="Anything due?", system="Answer.", timeout_s=20)
    events = [event async for event in asking.stream(request)]
    assert [event.type for event in events] == ["error"] and "could not be started" in (events[0].error or "")
    ok, message, _ = await claude_cli.probe(binary=found)  # Settings' "Run check" with that path
    expected = "could not be started" if broken == "not_executable" else "was not found"
    assert not ok and expected in message
    assert fake.calls == []


# --------------------------------------------------------------------------------------------------
# answers
# --------------------------------------------------------------------------------------------------


async def test_ask_streams_text_tool_calls_and_results(fake: FakeClaude) -> None:
    fake.play({"transcript": "ask_stream.jsonl"})
    request = LLMRequest(
        purpose="ask",
        prompt="When is the parking fine due?",
        system="Answer from the records.",
        tools=["mcp__ordnung__search"],
        allowed_tools=["mcp__ordnung__search"],
        mcp_config={"mcpServers": {"ordnung": {"command": "ordnung", "args": ["mcp"]}}},
        timeout_s=20,
    )
    events = [event async for event in ClaudeCLIBackend(max_retries=0).stream(request)]

    argv = fake.calls[0]["argv"]
    assert "--include-partial-messages" in argv
    assert argv[argv.index("--tools") + 1] == "mcp__ordnung__search"
    assert argv[argv.index("--allowedTools") + 1] == "mcp__ordnung__search"
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == request.mcp_config
    assert [event.type for event in events] == ["tool_use", "tool_result", "text", "text", "done"]
    assert (events[0].name, events[0].input) == ("mcp__ordnung__search", {"query": "parking"})
    assert events[1].text == "itm_parking · Pay parking fine · 25.00 EUR · due 2026-09-29"
    assert "".join(event.text or "" for event in events if event.type == "text") == (
        "The parking fine is due on 29 September."
    )
    done = events[-1].response
    assert done is not None and done.text == "The parking fine is due on 29 September." and done.data is None


async def test_json_in_the_text_is_used_when_structured_output_is_missing(
    fake: FakeClaude, letter: LLMRequest
) -> None:
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": f"Here it is:\n```json\n{json.dumps(ANSWER)}\n```",
    }
    fake.play({"lines": [json.dumps(result)]})
    assert (await ClaudeCLIBackend(max_retries=0).complete(letter)).data == ANSWER


async def test_an_answer_without_structured_output_is_retried_once(
    fake: FakeClaude, letter: LLMRequest
) -> None:
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "I can't read this letter.",
    }
    fake.play({"lines": [json.dumps(result)]})
    with pytest.raises(ClaudeBadOutput):
        await ClaudeCLIBackend(max_retries=0).complete(letter)
    assert len(fake.calls) == 2


# --------------------------------------------------------------------------------------------------
# errors (classified from the result event, not the exit code)
# --------------------------------------------------------------------------------------------------


async def test_a_usage_limit_pauses_until_the_reset(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"transcript": "usage_limit.jsonl", "exit": 1})
    with pytest.raises(ClaudeRateLimited) as caught:
        await ClaudeCLIBackend(max_retries=2).complete(letter)
    assert caught.value.reset_at == "5pm (Europe/Berlin)"
    assert len(fake.calls) == 1  # never hammered with retries


async def test_an_overloaded_api_pauses_like_a_rate_limit(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"transcript": "overloaded.jsonl", "exit": 1})
    with pytest.raises(ClaudeRateLimited) as caught:
        await ClaudeCLIBackend(max_retries=2).complete(letter)
    assert caught.value.reset_at is None  # the worker then waits its default pause
    assert len(fake.calls) == 1


async def test_a_login_problem_is_an_auth_error(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"transcript": "auth_error.jsonl", "exit": 1})
    with pytest.raises(ClaudeAuthError, match="not signed in"):
        await ClaudeCLIBackend(max_retries=2).complete(letter)
    assert len(fake.calls) == 1


async def test_a_server_error_is_retried(
    fake: FakeClaude, letter: LLMRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep = asyncio.sleep
    waits: list[float] = []

    async def no_wait(seconds: float) -> None:
        waits.append(seconds)
        await sleep(0)

    monkeypatch.setattr(claude_cli.asyncio, "sleep", no_wait)
    fake.play({"transcript": "api_error_500.jsonl", "exit": 1}, {"transcript": "extract_structured.jsonl"})
    response = await ClaudeCLIBackend(max_retries=2).complete(letter)
    assert response.data == ANSWER
    assert len(fake.calls) == 2 and waits == [2.0]


@pytest.mark.parametrize(
    ("subtype", "message"),
    [
        ("error_max_turns", "too many steps"),
        ("error_max_budget_usd", "cost cap"),
        ("error_during_execution", ""),
    ],
)
async def test_a_stopped_run_is_an_error(
    fake: FakeClaude, letter: LLMRequest, subtype: str, message: str
) -> None:
    result = {"type": "result", "subtype": subtype, "is_error": True, "num_turns": 9}
    fake.play({"lines": [json.dumps(result)], "exit": 1})
    with pytest.raises(LLMError, match=message or subtype) as caught:
        await ClaudeCLIBackend(max_retries=2).complete(letter.model_copy(update={"max_budget_usd": 0.5}))
    assert type(caught.value) is LLMError  # not retried, not a pause
    argv = fake.calls[0]["argv"]
    assert argv[argv.index("--max-budget-usd") + 1] == "0.50"
    assert len(fake.calls) == 1


async def test_a_crash_without_a_result_reports_stderr(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"stderr": "error: unknown option '--no-session-persistence'\n", "exit": 1})
    with pytest.raises(LLMError, match="unknown option"):
        await ClaudeCLIBackend(max_retries=0).complete(letter)


async def test_a_stream_reports_errors_as_an_event(fake: FakeClaude) -> None:
    fake.play({"transcript": "auth_error.jsonl", "exit": 1})
    request = LLMRequest(purpose="ask", prompt="Anything due?", system="Answer.", timeout_s=20)
    events = [event async for event in ClaudeCLIBackend(max_retries=0).stream(request)]
    assert [event.type for event in events] == ["error"]
    assert "not signed in" in (events[0].error or "")


async def test_the_doctor_probe(fake: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    """The probe runs on the model it is given — the one every call runs on, so a name Claude Code
    refuses fails at "Run check" and not on the next letter — else ``haiku``, and says which."""
    monkeypatch.delenv("ORDNUNG_CLAUDE_MODEL", raising=False)
    result = {"type": "result", "subtype": "success", "is_error": False, "result": "OK"}
    fake.play({"lines": [json.dumps(result)]})
    assert await claude_cli.probe() == (True, "OK", "haiku")
    argv = fake.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "haiku" and "--json-schema" not in argv
    fake.play({"lines": [json.dumps(result)]})
    assert await claude_cli.probe(model="claude-opus-5-5") == (True, "OK", "claude-opus-5-5")
    argv = fake.calls[1]["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    fake.play({"transcript": "auth_error.jsonl", "exit": 1})
    ok, message, model = await claude_cli.probe(model="claude-opus-5-5")
    assert not ok and "not signed in" in message and model == "claude-opus-5-5"


# --------------------------------------------------------------------------------------------------
# lines the backend can't use
# --------------------------------------------------------------------------------------------------


async def test_unreadable_lines_are_skipped(fake: FakeClaude, letter: LLMRequest) -> None:
    junk = ["Warning: something on stdout", "{not json", "[1, 2, 3]", "42", "null", ""]
    fake.play({"lines": junk, "transcript": "extract_structured.jsonl"})
    assert (await ClaudeCLIBackend(max_retries=0).complete(letter)).data == ANSWER


async def test_an_oversized_line_is_skipped(
    fake: FakeClaude, letter: LLMRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_cli, "_STREAM_LIMIT", 64 * 1024)  # the real limit is 32 MiB
    fake.play({"big_line": 300 * 1024, "transcript": "extract_structured.jsonl"})
    assert (await ClaudeCLIBackend(max_retries=0).complete(letter)).data == ANSWER


# --------------------------------------------------------------------------------------------------
# no process is left behind
# --------------------------------------------------------------------------------------------------


async def test_the_mcp_server_does_not_outlive_an_answer(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"child": True, "transcript": "extract_structured.jsonl"})
    assert (await ClaudeCLIBackend(max_retries=0).complete(letter)).data == ANSWER
    (call,) = fake.calls
    assert await _gone(call["pid"], call["child_pid"])


async def test_a_timeout_kills_the_whole_process_group(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"child": True, "lines": ['{"type": "system", "subtype": "init"}'], "hang": True})
    started = time.monotonic()
    with pytest.raises(ClaudeTimeout, match="did not answer within 1 s"):
        await ClaudeCLIBackend(max_retries=0).complete(letter.model_copy(update={"timeout_s": 1.0}))
    assert time.monotonic() - started < 10
    (call,) = fake.calls
    assert await _gone(call["pid"], call["child_pid"])


async def test_a_cli_that_never_reads_the_request_times_out(fake: FakeClaude, letter: LLMRequest) -> None:
    big = letter.attachments[0].path.parent / "big-scan.png"
    big.write_bytes(os.urandom(2 * 1024 * 1024))  # far more than a pipe holds
    request = letter.model_copy(
        update={"timeout_s": 1.0, "attachments": [Attachment(path=big, media_type="image/png")]}
    )
    fake.play({"read_stdin": False, "child": True})
    with pytest.raises(ClaudeTimeout, match="did not read the request"):
        await ClaudeCLIBackend(max_retries=0).complete(request)
    (call,) = fake.calls
    assert await _gone(call["pid"], call["child_pid"])


async def test_cancelling_a_call_kills_the_whole_process_group(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"child": True, "lines": ['{"type": "system", "subtype": "init"}'], "hang": True})
    # only the cancel ends this call: a call timeout must not, however slow a busy machine starts the fake
    long = letter.model_copy(update={"timeout_s": 600})
    task = asyncio.create_task(ClaudeCLIBackend(max_retries=0).complete(long))
    assert await _eventually(lambda: bool(fake.calls), within=10), "the fake claude never started"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (call,) = fake.calls
    assert await _gone(call["pid"], call["child_pid"])


async def test_stopping_a_stream_early_kills_the_process_group(fake: FakeClaude) -> None:
    """Ask's reader goes away (the browser closed the page) after the first event."""
    fake.play({"child": True, "transcript": "ask_stream.jsonl", "hang": True})
    request = LLMRequest(
        purpose="ask", prompt="When is the parking fine due?", system="Answer.", timeout_s=600
    )
    stream = ClaudeCLIBackend(max_retries=0).stream(request)
    first: StreamEvent = await anext(stream)
    assert first.type == "tool_use"
    await stream.aclose()
    (call,) = fake.calls
    assert await _gone(call["pid"], call["child_pid"])


# --------------------------------------------------------------------------------------------------
# tool calls of a complete() call (the benchmark's agent with a calculator)
# --------------------------------------------------------------------------------------------------


async def test_complete_returns_the_tool_calls_paired_by_id(fake: FakeClaude) -> None:
    """Parallel calls answer out of order, and the CLI's own StructuredOutput call is not a tool call."""
    fake.play({"transcript": "tool_calls_parallel.jsonl"})
    request = LLMRequest(
        purpose="eval_baseline",
        prompt="When is the objection due?",
        system="Answer.",
        schema={"type": "object", "properties": {"due_date": {"type": "string"}}},
        allowed_tools=["mcp__ordnung_rules__*"],
        mcp_config={"mcpServers": {"ordnung_rules": {"command": "python", "args": ["-m", "ordnung", "mcp"]}}},
        timeout_s=20,
    )
    response = await ClaudeCLIBackend(max_retries=0).complete(request)
    assert response.data == {"due_date": "2026-10-21"}
    deadline, iban = response.tool_calls
    assert deadline.name == "mcp__ordnung_rules__compute_deadline"
    assert deadline.input["document_date"] == "2026-09-15"
    assert json.loads(deadline.result or "")["due_date"] == "2026-10-21"  # not the IBAN answer
    assert iban.name == "mcp__ordnung_rules__check_iban" and json.loads(iban.result or "")["valid"] is True


async def test_complete_without_tools_has_no_tool_calls(fake: FakeClaude, letter: LLMRequest) -> None:
    fake.play({"transcript": "extract_structured.jsonl"})
    assert (await ClaudeCLIBackend(max_retries=0).complete(letter)).tool_calls == []


def test_translate_keeps_the_tool_use_ids() -> None:
    events = claude_cli.translate(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "mcp__ordnung__search",
                        "input": {"query": "x"},
                    },
                    {"type": "tool_use", "id": "toolu_2", "name": "StructuredOutput", "input": {}},
                ]
            },
        }
    )
    assert [(e.type, e.name, e.tool_use_id) for e in events] == [
        ("tool_use", "mcp__ordnung__search", "toolu_1")
    ]
    (result,) = claude_cli.translate(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}]},
        }
    )
    assert (result.type, result.text, result.tool_use_id) == ("tool_result", "ok", "toolu_1")


def test_tool_trace_pairs_by_id_and_falls_back_to_order() -> None:
    trace = claude_cli.ToolTrace()
    for event in (
        StreamEvent(type="tool_use", name="a", input={"n": 1}, tool_use_id="1"),
        StreamEvent(type="tool_use", name="b", input={}, tool_use_id="2"),
        StreamEvent(type="tool_result", text="for b", tool_use_id="2"),
        StreamEvent(type="tool_result", text="for nobody", tool_use_id="unknown"),
        StreamEvent(type="tool_result", text="for a", tool_use_id="1"),
        StreamEvent(type="text", text="thinking"),
    ):
        trace.add(event)
    assert [(c.name, c.input, c.result) for c in trace.calls] == [
        ("a", {"n": 1}, "for a"),
        ("b", {}, "for b"),
    ]

    legacy = claude_cli.ToolTrace()  # events recorded before ids were kept
    for event in (
        StreamEvent(type="tool_use", name="a"),
        StreamEvent(type="tool_use", name="b"),
        StreamEvent(type="tool_result", text="first"),
        StreamEvent(type="tool_result", text="second"),
        StreamEvent(type="tool_result", text="extra"),
    ):
        legacy.add(event)
    assert [(c.name, c.result) for c in legacy.calls] == [("a", "first"), ("b", "second")]


def test_the_environment_can_pin_the_model(fake: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    """ORDNUNG_CLAUDE_MODEL names the id every call uses, whatever alias the request carries (an
    alias moves with releases)."""
    request = LLMRequest(purpose="ask", prompt="Anything due?", system="Answer.")
    monkeypatch.delenv("ORDNUNG_CLAUDE_MODEL", raising=False)
    argv = ClaudeCLIBackend().build_args(request)
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"  # ordnung.llm.base.DEFAULT_MODEL
    monkeypatch.setenv("ORDNUNG_CLAUDE_MODEL", "claude-sonnet-5-5")
    argv = ClaudeCLIBackend().build_args(request)
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"


def test_the_chosen_model_beats_the_request_and_yields_to_the_environment(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model the person chose (Settings → Claude) is read when the call is made, so a new choice
    counts from the next call; it beats the request's alias, and only ORDNUNG_CLAUDE_MODEL beats it."""
    request = LLMRequest(purpose="brief", prompt="Today?", system="Answer.", model="haiku")
    monkeypatch.delenv("ORDNUNG_CLAUDE_MODEL", raising=False)
    chosen = {"model": "claude-opus-5-5"}
    backend = ClaudeCLIBackend(model_setting=lambda: chosen["model"])
    assert backend.model_for(request) == "claude-opus-5-5"
    argv = backend.build_args(request)
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    chosen["model"] = "sonnet"  # saved meanwhile: the next call uses it, nothing is rebuilt
    assert backend.build_args(request)[argv.index("--model") + 1] == "sonnet"
    monkeypatch.setenv("ORDNUNG_CLAUDE_MODEL", "claude-sonnet-5")
    assert backend.model_for(request) == "claude-sonnet-5"
    monkeypatch.delenv("ORDNUNG_CLAUDE_MODEL")
    # no setting at all (the doctor probe, the benchmarks): the request's own model
    assert ClaudeCLIBackend().model_for(request) == "haiku"


async def test_the_answer_names_the_model_the_call_ran_on(fake: FakeClaude) -> None:
    """When the CLI's result carries no ``modelUsage``, the answer (and so the usage log and the trace)
    names the model the call was made with — the chosen one, not the request's alias."""
    fake.play({"lines": [json.dumps({"type": "result", "subtype": "success", "result": "OK"})]})
    request = LLMRequest(purpose="brief", prompt="Today?", system="Answer.", model="haiku")
    backend = ClaudeCLIBackend(max_retries=0, model_setting=lambda: "claude-opus-5-5")
    response = await backend.complete(request)
    assert response.text == "OK" and response.model == "claude-opus-5-5"
