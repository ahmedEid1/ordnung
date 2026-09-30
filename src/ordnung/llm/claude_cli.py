"""Backend that drives the user's own, locally installed Claude Code CLI in headless mode.

Design notes
------------
* **Nothing sensitive on the command line.** The prompt and any attachments (page images, PDFs) are
  written to the CLI's stdin as one ``stream-json`` user message. argv only carries flags, so private
  letter text never shows up in ``ps`` and long documents cannot hit the kernel's 128 KiB per-argument
  limit.
* **No tools unless asked.** Extraction and transcription run with ``--tools ""``: the model sees the
  document as content blocks and can do nothing but answer. Ask gets only Ordnung's read-only MCP tools.
  No call ever uses ``--dangerously-skip-permissions``.
* **The model.** Each request names a model id (:data:`ordnung.llm.base.DEFAULT_MODEL`, a pinned id:
  an alias such as ``sonnet`` moves with releases, recordings are made with one model);
  ``ORDNUNG_CLAUDE_MODEL`` overrides it for every call, as ``ORDNUNG_CLAUDE_BIN`` picks the binary.
* **Isolation.** ``--setting-sources ""`` ignores the user's hooks/settings, ``--strict-mcp-config``
  keeps the user's own MCP servers out, ``--system-prompt`` replaces the coding-assistant prompt, and
  ``--no-session-persistence`` keeps calls out of the user's history. Never ``--bare`` (it disables
  subscription login).
* **Structured output.** ``--json-schema`` makes the CLI validate the final answer; we read
  ``structured_output`` from the ``result`` event.
* **Errors are classified from the result object**, not the exit code.
* Credentials are never touched — the CLI uses whatever login the user configured.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import signal
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ordnung.llm.base import (
    INTERACTIVE_PURPOSES,
    ClaudeAuthError,
    ClaudeBadOutput,
    ClaudeNotInstalled,
    ClaudeRateLimited,
    ClaudeTimeout,
    LLMError,
    LLMRequest,
    LLMResponse,
    StreamEvent,
    ToolCall,
    Usage,
)

_RATE_LIMIT_RE = re.compile(
    r"rate.?limit|usage limit|limit reached|overloaded|too many requests|out of (extra )?usage", re.I
)
_AUTH_RE = re.compile(
    r"not logged in|invalid api key|please run /login|authentication|unauthori[sz]ed|oauth token", re.I
)
_RESET_RE = re.compile(r"reset[s]? (?:at|in)\s+([^.\n|]+)", re.I)
_STREAM_LIMIT = 32 * 1024 * 1024
_STDERR_KEEP = 64 * 1024  # only the end of stderr is ever shown
_EXIT_WAIT_S = 30.0  # how long an answered call may take to exit


class TransientError(LLMError):
    """A 5xx API error — worth retrying quickly (an overloaded API pauses like a rate limit)."""


def find_claude(binary: str | None = None) -> str | None:
    candidate = binary or os.environ.get("ORDNUNG_CLAUDE_BIN") or "claude"
    if os.path.sep in candidate:
        return candidate if Path(candidate).exists() else None
    return shutil.which(candidate)


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort: parse a JSON object from free text (fenced or bare)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def usage_from(result: dict[str, Any]) -> Usage:
    u = result.get("usage") or {}
    return Usage(
        input_tokens=int(u.get("input_tokens") or 0),
        output_tokens=int(u.get("output_tokens") or 0),
        cache_read_tokens=int(u.get("cache_read_input_tokens") or 0),
        cache_creation_tokens=int(u.get("cache_creation_input_tokens") or 0),
        cost_usd=float(result.get("total_cost_usd") or 0.0),
        duration_ms=int(result.get("duration_ms") or 0),
        turns=int(result.get("num_turns") or 0),
    )


def served_model(result: dict[str, Any], fallback: str) -> str:
    usage = result.get("modelUsage") or {}
    if isinstance(usage, dict) and usage:
        return str(next(iter(usage.keys())))
    return fallback


def classify_result(result: dict[str, Any], stderr: str = "") -> LLMError | None:
    """Map a CLI ``result`` event to an error, or ``None`` if it succeeded."""
    status = result.get("api_error_status")
    subtype = str(result.get("subtype") or "")
    if not result.get("is_error") and subtype in ("", "success") and status in (None, 200):
        return None
    text = " ".join(str(x) for x in (result.get("result"), result.get("terminal_reason"), stderr) if x)
    if status in (401, 403) or _AUTH_RE.search(text):
        return ClaudeAuthError(
            "Claude Code is not signed in (or the key is invalid). Run “claude” once in a terminal and sign in."
        )
    if status == 429 or _RATE_LIMIT_RE.search(text):
        m = _RESET_RE.search(text)
        return ClaudeRateLimited(
            "Your Claude usage limit or a rate limit was reached. Ordnung will continue when it resets.",
            reset_at=m.group(1).strip() if m else None,
        )
    if isinstance(status, int) and status >= 500:
        return TransientError(f"Claude API error {status}")
    if subtype == "error_max_budget_usd":
        return LLMError("This request hit its cost cap and was stopped.")
    if subtype == "error_max_turns":
        return LLMError("The assistant needed too many steps and was stopped.")
    return LLMError((text or subtype or "claude reported an error").strip()[:500])


def build_user_message(req: LLMRequest) -> tuple[str, int]:
    """Return the stream-json line for stdin and the number of bytes of content it carries."""
    content: list[dict[str, Any]] = [{"type": "text", "text": req.prompt}]
    nbytes = len(req.prompt.encode("utf-8"))
    for att in req.attachments:
        data = Path(att.path).read_bytes()
        nbytes += len(data)
        block_type = "document" if att.media_type == "application/pdf" else "image"
        content.append(
            {
                "type": block_type,
                "source": {
                    "type": "base64",
                    "media_type": att.media_type,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
        )
    msg = {"type": "user", "message": {"role": "user", "content": content}}
    return json.dumps(msg, ensure_ascii=False) + "\n", nbytes


def _tail(text: str, n: int = 600) -> str:
    return text.strip()[-n:]


def translate(msg: dict[str, Any]) -> list[StreamEvent]:
    """Translate one CLI stream-json event into zero or more :class:`StreamEvent`s."""
    kind = msg.get("type")
    if kind == "stream_event":
        ev = msg.get("event") or {}
        if ev.get("type") == "content_block_delta":
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [StreamEvent(type="text", text=delta["text"])]
        return []
    if kind == "assistant":
        out = []
        for block in (msg.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") != "StructuredOutput":
                out.append(
                    StreamEvent(
                        type="tool_use",
                        name=block.get("name"),
                        input=block.get("input"),
                        tool_use_id=block.get("id"),
                    )
                )
        return out
    if kind == "user":
        out = []
        content = (msg.get("message") or {}).get("content") or []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    body = block.get("content")
                    if isinstance(body, list):
                        body = "".join(c.get("text", "") for c in body if isinstance(c, dict))
                    # whole, as the model read it: Ask checks its answer against this text (ADR 0008),
                    # and Ordnung's MCP tools keep each result within channels.RESULT_BUDGET themselves
                    out.append(
                        StreamEvent(type="tool_result", text=str(body), tool_use_id=block.get("tool_use_id"))
                    )
        return out
    return []


class ToolTrace:
    """Pairs ``tool_use`` and ``tool_result`` events into :class:`ToolCall` objects, in call order.

    A result belongs to the call with its ``tool_use_id``: parallel calls may answer out of order.
    A result for a call that is not traced (the CLI's own ``StructuredOutput`` tool) is dropped.
    Events without ids (fakes, older recordings) pair with the oldest call still waiting.
    """

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._by_id: dict[str, int] = {}

    def add(self, ev: StreamEvent) -> None:
        if ev.type == "tool_use":
            if ev.tool_use_id:
                self._by_id[ev.tool_use_id] = len(self.calls)
            self.calls.append(ToolCall(name=ev.name or "", input=dict(ev.input or {})))
        elif ev.type == "tool_result":
            if ev.tool_use_id:
                index = self._by_id.pop(ev.tool_use_id, None)
            else:
                index = next((i for i, call in enumerate(self.calls) if call.result is None), None)
            if index is not None:
                self.calls[index].result = ev.text


class ClaudeCLIBackend:
    """Runs ``claude -p`` as a subprocess. Safe to share across tasks.

    Two lanes keep the app responsive: interactive purposes (ask, draft, brief…) never wait behind a
    bulk import (transcribe/extract/review).
    """

    name = "claude"

    def __init__(
        self,
        binary: str | None = None,
        concurrency: int = 2,
        interactive_concurrency: int = 1,
        max_retries: int = 2,
    ) -> None:
        self.binary = find_claude(binary)
        self._background = asyncio.Semaphore(max(1, concurrency))
        self._interactive = asyncio.Semaphore(max(1, interactive_concurrency))
        self.max_retries = max_retries

    def _lane(self, req: LLMRequest) -> asyncio.Semaphore:
        return self._interactive if req.purpose in INTERACTIVE_PURPOSES else self._background

    def _require_binary(self) -> str:
        if not self.binary:
            raise ClaudeNotInstalled(
                "The “claude” command was not found. Install Claude Code (https://claude.com/claude-code), "
                "sign in by running “claude” once, then try again."
            )
        return self.binary

    def build_args(self, req: LLMRequest, *, partial: bool = False) -> list[str]:
        args = [
            self._require_binary(),
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            os.environ.get("ORDNUNG_CLAUDE_MODEL") or req.model,  # a pinned id beats the request's alias
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--system-prompt",
            req.system,
            "--tools",
            ",".join(req.tools),
        ]
        if partial:
            args.append("--include-partial-messages")
        if req.allowed_tools:
            args += ["--allowedTools", ",".join(req.allowed_tools)]
        if req.schema_:
            args += ["--json-schema", json.dumps(req.schema_, separators=(",", ":"))]
        if req.mcp_config:
            args += ["--mcp-config", json.dumps(req.mcp_config)]
        if req.max_budget_usd:
            args += ["--max-budget-usd", f"{req.max_budget_usd:.2f}"]
        return args

    async def complete(self, req: LLMRequest) -> LLMResponse:
        attempt = 0
        bad_output_retried = False
        while True:
            try:
                async with self._lane(req):
                    return await self._complete_once(req)
            except (TransientError, ClaudeTimeout):
                attempt += 1
                if attempt > self.max_retries:
                    raise
                await asyncio.sleep(min(20.0, 2.0 * 2 ** (attempt - 1)))
            except ClaudeBadOutput:
                if bad_output_retried:
                    raise
                bad_output_retried = True

    async def _complete_once(self, req: LLMRequest) -> LLMResponse:
        final: LLMResponse | None = None
        calls = ToolTrace()
        async for ev in self._run(req, partial=False):
            if ev.type == "done":
                final = ev.response
            else:
                calls.add(ev)
        if final is None:  # pragma: no cover - _run always ends with done or raises
            raise LLMError("Claude ended without a result")
        final.tool_calls = calls.calls
        return final

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        async with self._lane(req):
            try:
                async for ev in self._run(req, partial=True):
                    yield ev
            except LLMError as exc:
                yield StreamEvent(type="error", error=str(exc))

    async def _run(self, req: LLMRequest, *, partial: bool) -> AsyncIterator[StreamEvent]:
        """Spawn the CLI, feed stdin, translate stdout events. Ends with a ``done`` event or raises."""
        args = self.build_args(req, partial=partial)
        line, _nbytes = build_user_message(req)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="ordnung-llm-") as cwd:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT,
                start_new_session=True,  # own process group → we can kill MCP children too
            )
            assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
            stderr_task = asyncio.create_task(_read_tail(proc.stderr, _STDERR_KEEP))
            result: dict[str, Any] | None = None
            deadline = started + req.timeout_s
            try:
                proc.stdin.write(line.encode("utf-8"))
                try:
                    await asyncio.wait_for(proc.stdin.drain(), timeout=req.timeout_s)
                except TimeoutError as exc:
                    raise ClaudeTimeout(
                        f"Claude did not read the request within {int(req.timeout_s)} s"
                    ) from exc
                proc.stdin.close()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ClaudeTimeout(f"Claude did not answer within {int(req.timeout_s)} s")
                    try:
                        raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                    except TimeoutError as exc:
                        raise ClaudeTimeout(f"Claude did not answer within {int(req.timeout_s)} s") from exc
                    except ValueError:  # a line over _STREAM_LIMIT (dropped by the reader): skip it
                        continue
                    if not raw:
                        break
                    try:
                        msg = json.loads(raw)
                    except ValueError:  # not JSON (or not UTF-8): a stray line, not an event
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("type") == "result":
                        result = msg
                        continue
                    for ev in translate(msg):
                        yield ev
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_EXIT_WAIT_S)
                except TimeoutError as exc:
                    raise ClaudeTimeout("Claude did not exit after answering") from exc
                _kill_group(proc)  # MCP servers it started must not outlive it
            except BaseException:
                await _kill(proc)
                stderr_task.cancel()
                raise
            stderr = (await stderr_task).decode("utf-8", "replace")

        if result is None:
            raise LLMError(_tail(stderr) or "Claude exited without an answer")
        err = classify_result(result, _tail(stderr))
        if err is not None:
            raise err
        text = str(result.get("result") or "")
        data: dict[str, Any] | None = None
        if req.schema_ is not None:
            so = result.get("structured_output")
            data = so if isinstance(so, dict) else extract_json(text)
            if data is None:
                raise ClaudeBadOutput("Claude returned no structured output")
        usage = usage_from(result)
        if not usage.duration_ms:
            usage.duration_ms = int((time.monotonic() - started) * 1000)
        yield StreamEvent(
            type="done",
            response=LLMResponse(
                text=text, data=data, usage=usage, model=served_model(result, req.model), backend=self.name
            ),
        )


async def _read_tail(stream: asyncio.StreamReader, keep: int) -> bytes:
    """Read ``stream`` to its end (so the child never blocks on a full pipe), keeping the last bytes."""
    tail = b""
    while chunk := await stream.read(65536):
        tail = (tail + chunk)[-keep:]
    return tail


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    """Kill the process group ``claude`` leads (its MCP server included) — POSIX only."""
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)


async def _kill_tree_windows(pid: int) -> None:
    """``taskkill /T``: Windows has no process groups to signal, so end the process tree by id."""
    with contextlib.suppress(OSError):
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/F",
            "/T",
            "/PID",
            str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(killer.wait(), timeout=10)


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """Stop ``claude`` and everything it started, on any platform (never masking the original error)."""
    if proc.returncode is None:
        if os.name == "posix":
            _kill_group(proc)
        else:
            await _kill_tree_windows(proc.pid)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(Exception):
        await proc.wait()


async def run_cli_json(args: list[str], timeout_s: float = 20) -> dict[str, Any] | None:
    """Run a short CLI command that prints JSON (e.g. ``claude auth status``)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except (OSError, TimeoutError):
        return None
    try:
        value = json.loads(out.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def version(binary: str | None = None) -> str | None:
    path = find_claude(binary)
    if not path:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            path, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except (OSError, TimeoutError):
        return None
    return out.decode().strip() or None


async def auth_status(binary: str | None = None) -> dict[str, Any] | None:
    """Zero-token login check via ``claude auth status`` (JSON)."""
    path = find_claude(binary)
    if not path:
        return None
    return await run_cli_json([path, "auth", "status"])


async def probe(binary: str | None = None, timeout_s: float = 60) -> tuple[bool, str]:
    """One tiny live call (used by ``ordnung doctor --probe``)."""
    backend = ClaudeCLIBackend(binary=binary, concurrency=1, max_retries=0)
    try:
        resp = await backend.complete(
            LLMRequest(
                purpose="doctor",
                prompt="Reply with exactly: OK",
                system="You are a health check. Reply with exactly: OK",
                model="haiku",
                timeout_s=timeout_s,
            )
        )
    except LLMError as exc:
        return False, str(exc)
    return ("OK" in resp.text.upper()), resp.text.strip()[:80]
