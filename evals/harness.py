"""Safe, repeated recording and exact replay for the benchmarks (``python -m evals.harness``).

The wrappers here sit in the backend stack the benchmark runner builds (``evals/run.py``'s ``make_backend``); the
Ask benchmark takes the same ones (``evals/ask``). From the outside in:

* :class:`RepeatKey` — **the run index** (``--repeat N``). Run 1 is untouched; run N ≥ 2 gives every request the
  ``cache_key`` ``<cache_key or sha256(prompt)>|repeat=N``, so it is recorded and replayed under keys of its own
  while the ``claude`` CLI gets the very same argv and stdin (``cache_key`` is never sent). A repeat can never be
  answered from run 1's recordings.
* :class:`LockedRequests` — **the request lock**, ``requests.lock.json`` beside the recordings. A replay key holds
  what identifies a request's input, not every byte the model reads; the lock maps each recording's key to a hash
  of everything the CLI gets (:func:`request_content`). A replayed request whose hash differs is a
  :class:`StaleRecording`; a recording the lock doesn't know is an :class:`UnlockedRecording` (both fail the
  prediction, loudly). A live recording writes the entry with its cassette. Without a lock file (a scratch
  folder) nothing is checked.
* :class:`LiveCalls` — around the live ``claude`` only: the **budget stop** (``--max-cost-usd``: no new call once
  the run's live spend reaches it), **waiting through a usage limit** (``--wait-on-limit``: until the reset the CLI
  names plus 2 minutes, else 30 minutes; no probe call) and **the ledger**, one line per live call in
  ``ledger.jsonl`` beside the recordings.
* :class:`RecorderLock` — **one recorder at a time** (``evals/recorded/.recording.lock``, gitignored); a lock left by
  a recorder that died is freed only on purpose, with ``python -m evals.harness unlock``.

Commands (zero tokens; none calls a model):

* ``lock-requests [--ask] [--check | --write]`` — replay every recorded split (or the Ask benchmark) and compare
  each request with the lock, or write the entries (merged: an entry is never dropped);
* ``diff-requests [REF] [--ask]`` — which requests changed since the lock at ``REF``, and in which part
  (system, prompt, schema, attachments, tools …): "is this refactor a re-record?";
* ``ledger [FILE …]`` — what a recording cost, in calls and dollars, from its ledger;
* ``unlock`` — free the recorder lock of a recorder that is no longer running;
* ``smoke --scratch DIR`` — the live smoke before a paid recording (it calls the model: a few cents), into a
  scratch folder that is thrown away.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung.llm import claude_cli
from ordnung.llm.base import (
    DEFAULT_MODEL,
    ClaudeAuthError,
    ClaudeBadOutput,
    ClaudeNotInstalled,
    ClaudeRateLimited,
    ClaudeTimeout,
    LLMBackend,
    LLMError,
    LLMRequest,
    LLMResponse,
    ReplayMiss,
    StreamEvent,
)
from ordnung.llm.replay import fixture_path, write_atomic
from ordnung.llm.runtime import request_key

EVALS_DIR = Path(__file__).resolve().parent
ROOT = EVALS_DIR.parent
RECORDED_DIR = EVALS_DIR / "recorded"
ASK_RECORDED_DIR = RECORDED_DIR / "ask"
LOCK_FILE = "requests.lock.json"
LEDGER_FILE = "ledger.jsonl"
RECORDER_LOCK_NAME = ".recording.lock"
#: The one recorder lock every live recording takes from the command line (``--recorded-dir`` or not).
RECORDER_LOCK = RECORDED_DIR / RECORDER_LOCK_NAME
HOST = socket.gethostname()
#: How long after the reset the CLI names a waiting run tries again, and how long it waits without one.
WAIT_MARGIN = timedelta(minutes=2)
WAIT_UNKNOWN = timedelta(minutes=30)
#: The parts of a request the CLI gets, as :func:`request_content` names them.
FIELDS = ("model", "system", "prompt", "schema", "tools", "mcp", "allowed_tools", "budget", "attachments")
STALE = "stale recording"
UNLOCKED = "unlocked recording"
#: The smoke's letters: a phone photo (transcribed; attached as an image for the baselines) and a text letter.
SMOKE_IDS = ("dev-invoice_relative-A1-photo", "dev-tax_assessment-A1")


class HarnessError(RuntimeError):
    """A harness command cannot do what it was asked (the message says why)."""


def _now() -> datetime:
    """The time (UTC); tests move it."""
    return datetime.now(UTC)


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------------------------------
# The run index
# --------------------------------------------------------------------------------------------------


def repeat_request(req: LLMRequest, repeat: int) -> LLMRequest:
    """``req`` as run ``repeat`` makes it: run 1 unchanged, run N ≥ 2 with ``cache_key`` ``<basis>|repeat=N``
    (``basis``: the request's ``cache_key``, else the sha256 of its prompt, which is what the key held)."""
    if repeat < 1:
        raise ValueError(f"a repeat counts from 1, not {repeat}")
    if repeat == 1:
        return req
    return req.model_copy(update={"cache_key": f"{_basis(req)}|repeat={repeat}"})


def _basis(req: LLMRequest) -> str:
    return (
        req.cache_key if req.cache_key is not None else hashlib.sha256(req.prompt.encode("utf-8")).hexdigest()
    )


def first_run(req: LLMRequest, repeat: int) -> LLMRequest:
    """The run-1 request a repeat's request repeats (undoes :func:`repeat_request`)."""
    suffix = f"|repeat={repeat}"
    if repeat == 1 or req.cache_key is None or not req.cache_key.endswith(suffix):
        return req
    basis = req.cache_key.removesuffix(suffix)
    prompt_sha = hashlib.sha256(req.prompt.encode("utf-8")).hexdigest()
    return req.model_copy(update={"cache_key": None if basis == prompt_sha else basis})


def repeat_suffix(repeat: int) -> str:
    """The results file's suffix for a repeat: ``""`` for run 1, else ``-r<N>``."""
    return "" if repeat == 1 else f"-r{repeat}"


class RepeatKey:
    """Gives run ``repeat`` (≥ 2) replay and record keys of its own; run 1 passes through unchanged."""

    def __init__(self, inner: LLMBackend, repeat: int) -> None:
        if repeat < 1:
            raise ValueError(f"a repeat counts from 1, not {repeat}")
        self.inner = inner
        self.repeat = repeat
        self.name = inner.name

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return await self.inner.complete(repeat_request(req, self.repeat))

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        async for event in self.inner.stream(repeat_request(req, self.repeat)):
            yield event


# --------------------------------------------------------------------------------------------------
# What the CLI gets, and the request lock
# --------------------------------------------------------------------------------------------------


def normalized_mcp(config: Mapping[str, Any] | None) -> Any:
    """The MCP config as far as the model can tell: the interpreter that starts a server (``sys.executable``, which
    differs between machines and venvs) and the data folder Ask's server reads (a fresh temporary folder each
    run) are placeholders; the server, its arguments and its environment stay."""

    def walk(value: Any, key: str | None = None) -> Any:
        if isinstance(value, Mapping):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            out: list[Any] = []
            for item in value:
                out.append("<data-dir>" if out and out[-1] == "--data-dir" else walk(item))
            return out
        if key == "command" and isinstance(value, str) and Path(value).name.lower().startswith("python"):
            return "<python>"
        return value

    return None if config is None else walk(config)


def request_content(req: LLMRequest) -> dict[str, Any]:
    """Everything the ``claude`` CLI gets for ``req`` (its argv and stdin, :meth:`ClaudeCLIBackend.build_args` and
    :func:`~ordnung.llm.claude_cli.build_user_message`), by part. Not sent, so not here: ``cache_key``,
    ``prompt_version``, ``doc_ids``, the timeout. Attachments count by media type and the sha256 of their bytes."""
    return {
        "model": req.model,
        "system": req.system,
        "prompt": req.prompt,
        "schema": req.schema_,
        "tools": list(req.tools),
        "mcp": normalized_mcp(req.mcp_config),
        "allowed_tools": list(req.allowed_tools),
        "budget": req.max_budget_usd,
        "attachments": [
            [attachment.media_type, hashlib.sha256(Path(attachment.path).read_bytes()).hexdigest()]
            for attachment in req.attachments
        ],
    }


def request_sha256(req: LLMRequest) -> str:
    """The sha256 of :func:`request_content`."""
    return hashlib.sha256(_canonical(request_content(req))).hexdigest()


def _part_hashes(content: Mapping[str, Any]) -> dict[str, str]:
    return {name: hashlib.sha256(_canonical(content[name])).hexdigest()[:6] for name in FIELDS}


def request_fields(req: LLMRequest) -> dict[str, str]:
    """A short hash of each part of :func:`request_content` (what ``diff-requests`` names when one changed)."""
    return _part_hashes(request_content(req))


def entry_fields(entry: Mapping[str, Any]) -> dict[str, str]:
    """An entry's part hashes by name (the lock stores them as one string, in :data:`FIELDS` order)."""
    stored = entry.get("fields")
    if isinstance(stored, Mapping):
        return {str(name): str(value) for name, value in stored.items()}
    return dict(zip(FIELDS, str(stored or "").split(), strict=False))


def lock_key(req: LLMRequest) -> str:
    """``<purpose>/<key[:24]>``: the recording's path below its model's folder, without ``.json``."""
    return f"{req.purpose}/{request_key(req)[:24]}"


def lock_entry(req: LLMRequest, *, repeat: int = 1) -> dict[str, Any]:
    """The lock's entry for ``req``: its letters, the hash of everything the CLI gets (``content``, 128 bits) and
    a short hash of each part (``fields``, in :data:`FIELDS` order); for a repeat, the run and the run-1 entry it
    repeats (``of``). Its purpose is its key's first part."""
    content = request_content(req)
    parts = _part_hashes(content)
    entry: dict[str, Any] = {
        "docs": list(req.doc_ids),
        "content": hashlib.sha256(_canonical(content)).hexdigest()[:32],
        "fields": " ".join(parts[name] for name in FIELDS),
    }
    if repeat > 1:
        entry["repeat"] = repeat
        entry["of"] = lock_key(first_run(req, repeat))
    return entry


def lock_path(recorded_dir: Path, model: str = DEFAULT_MODEL) -> Path:
    """Where the request lock of ``model``'s recordings in ``recorded_dir`` lives."""
    from evals.run import safe_name

    return recorded_dir / safe_name(model) / LOCK_FILE


def dumps_lock(entries: Mapping[str, Mapping[str, Any]]) -> str:
    """The lock file's text: one entry per line, sorted, so that a change is a readable diff."""
    if not entries:
        return "{}\n"
    lines = [
        f"{json.dumps(key)}: {json.dumps(entries[key], sort_keys=True, separators=(',', ':'))}"
        for key in sorted(entries)
    ]
    return "{\n" + ",\n".join(lines) + "\n}\n"


class RequestLock:
    """``requests.lock.json``: lock key → :func:`lock_entry` of the request each recording answered."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.exists = self.path.is_file()
        self.entries: dict[str, dict[str, Any]] = {}
        if self.exists:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise HarnessError(f"{self.path} is not a request lock")
            self.entries = {str(key): dict(value) for key, value in data.items()}

    def get(self, key: str) -> dict[str, Any] | None:
        return self.entries.get(key)

    def put(self, key: str, entry: dict[str, Any]) -> None:
        self.entries[key] = entry
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self.path, dumps_lock(self.entries))
        self.exists = True


class StaleRecording(ReplayMiss):
    """A recorded request whose content changed under the same key: replaying it would score the answer to a
    request no longer sent."""


class UnlockedRecording(ReplayMiss):
    """A recording the request lock doesn't know (made outside the harness, or before the lock was backfilled)."""


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_ino


class LockedRequests:
    """Checks every request against the request lock before it is replayed, and locks what a recorder records.

    ``record``: a live (replay-first) stack below, whose new recordings get their entry the moment their cassette
    is written; ``refresh``: everything is recorded anew, so nothing is checked and every entry is rewritten.
    """

    def __init__(
        self,
        inner: LLMBackend,
        lock: RequestLock,
        *,
        root: Path,
        record: bool = False,
        refresh: bool = False,
        repeat: int = 1,
    ) -> None:
        self.inner = inner
        self.lock = lock
        self.root = Path(root)
        self.record = record
        self.refresh = refresh
        self.repeat = repeat
        self.name = inner.name

    def _paths(self, req: LLMRequest) -> tuple[Path, Path]:
        path = fixture_path(self.root, req)
        return path, path.with_suffix(".failure.json")

    def _stamps(self, req: LLMRequest) -> tuple[tuple[int, int] | None, ...]:
        return tuple(_stamp(path) for path in self._paths(req))

    def check(self, req: LLMRequest) -> tuple[str, dict[str, Any]]:
        """Raise :class:`StaleRecording` or :class:`UnlockedRecording` for a request the lock says must not be
        replayed; return its key and fresh entry."""
        key = lock_key(req)
        entry = lock_entry(req, repeat=self.repeat)
        if self.refresh or not self.lock.exists:
            return key, entry
        docs = ", ".join(req.doc_ids) or "no letter"
        known = self.lock.get(key)
        if known is not None:
            if known.get("content") != entry["content"]:
                was, now = entry_fields(known), entry_fields(entry)
                changed = [name for name in FIELDS if was.get(name) != now.get(name)]
                raise StaleRecording(
                    f"{STALE}: {req.purpose} for {docs} ({key}) differs from {LOCK_FILE} in: "
                    f"{', '.join(changed) or 'its content'} — undo the change, or record it again on purpose "
                    "(--live --refresh) and publish the change"
                )
        elif any(stamp is not None for stamp in self._stamps(req)):
            raise UnlockedRecording(
                f"{UNLOCKED}: {req.purpose} for {docs} ({key}) is not in {LOCK_FILE} — backfill the lock by replay "
                "(python -m evals.harness lock-requests --write) or record it again"
            )
        return key, entry

    def _locked(self, req: LLMRequest, key: str, entry: dict[str, Any], before: tuple[Any, ...]) -> None:
        if self.record and self._stamps(req) != before and any(self._stamps(req)):
            self.lock.put(key, entry)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        key, entry = self.check(req)
        before = self._stamps(req)
        try:
            response = await self.inner.complete(req)
        except ClaudeBadOutput:  # a recorded model failure is a recording too
            self._locked(req, key, entry, before)
            raise
        self._locked(req, key, entry, before)
        return response

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        try:
            key, entry = self.check(req)
        except ReplayMiss as exc:
            yield StreamEvent(type="error", error=str(exc))
            return
        before = self._stamps(req)
        async for event in self.inner.stream(req):
            yield event
        self._locked(req, key, entry, before)


_KEY_IN_MESSAGE = re.compile(r"\((\w+/[0-9a-f]{24})\)")


def _keys(errors: Sequence[str | None], prefix: str) -> list[str]:
    found = {
        match.group(1)
        for error in errors
        if error and error.startswith(prefix) and (match := _KEY_IN_MESSAGE.search(error))
    }
    return sorted(found)


def drift_lines(model: str, errors: Sequence[str | None], lock: Path) -> list[str]:
    """What a run says when requests differ from the lock (``errors``: its predictions' errors)."""
    stale = _keys(errors, STALE)
    unlocked = _keys(errors, UNLOCKED)
    lines = []
    if stale:
        purposes = Counter(key.split("/")[0] for key in stale)
        listed = ", ".join(f"{purpose} {count}" for purpose, count in sorted(purposes.items()))
        lines.append(
            f"{model}: {len(stale)} request(s) differ from {lock} under the same key ({listed}): a replay would score "
            "answers to requests no longer sent. See what changed with `python -m evals.harness diff-requests HEAD`; "
            "then record those again on purpose, or publish the numbers as measured on the earlier request text."
        )
    if unlocked:
        lines.append(
            f"{model}: {len(unlocked)} recording(s) are not in {lock}: backfill it by replay with "
            "`python -m evals.harness lock-requests --write` (and review the diff)."
        )
    return lines


# --------------------------------------------------------------------------------------------------
# Live calls: the budget, waiting through a usage limit, the ledger
# --------------------------------------------------------------------------------------------------


class BudgetReached(LLMError):
    """The run's live spend reached ``--max-cost-usd``: no new call is started (what is done is kept)."""


class Budget:
    """The run's live spend against its cap (``--max-cost-usd``); replayed answers cost nothing. ``spent`` starts at
    what this step already spent (:func:`ledger_spent`), so resuming with the same command gets no new cap."""

    def __init__(self, cap: float, *, spent: float = 0.0) -> None:
        if cap < 0:
            raise ValueError("a budget is not negative")
        self.cap = cap
        self.spent = max(0.0, spent)

    @property
    def reached(self) -> bool:
        return self.spent >= self.cap

    def message(self) -> str:
        return (
            f"budget reached: ${self.spent:.4f} spent of --max-cost-usd {self.cap:g} (counting this step's earlier "
            "calls in its ledger); what is recorded is kept — resume with a higher --max-cost-usd"
        )

    def check(self) -> None:
        if self.reached:
            raise BudgetReached(self.message())

    def add(self, cost: float) -> None:
        self.spent += max(0.0, cost)


_RELATIVE = re.compile(r"(?:(\d+)\s*(?:hours?|hrs?|h)\b)?\s*(?:(\d+)\s*(?:minutes?|mins?|m)\b)?", re.I)
_CLOCK = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(?\s*([A-Za-z_]+(?:/[A-Za-z_+-]+)*)\s*\)?)?", re.I
)


def parse_reset(text: str | None, now: datetime, *, local: tzinfo | None = None) -> datetime | None:
    """When a usage limit resets, from what the CLI says (``reset_at``: "3pm (Europe/Berlin)", "15:00 UTC",
    "2 hours", an ISO time or epoch seconds), as an aware UTC time; ``None`` when it names none. A clock time
    without a zone is read in ``local`` (default: this computer's zone), and one already past today is tomorrow's."""
    if not text or not text.strip():
        return None
    value = text.strip()
    if re.fullmatch(r"\d{9,11}", value):
        return datetime.fromtimestamp(int(value), UTC)
    with contextlib.suppress(ValueError):
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
        zone = local or now.astimezone().tzinfo or UTC
        return (found if found.tzinfo else found.replace(tzinfo=zone)).astimezone(UTC)
    relative = _RELATIVE.fullmatch(value)
    if relative and (relative.group(1) or relative.group(2)):
        return now + timedelta(hours=int(relative.group(1) or 0), minutes=int(relative.group(2) or 0))
    clock = _CLOCK.fullmatch(value)
    if clock is None:
        return None
    hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
    meridiem = (clock.group(3) or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    name = clock.group(4)
    zone_info: tzinfo
    if name is None:
        zone_info = local or now.astimezone().tzinfo or UTC
    elif name.upper() in ("UTC", "GMT", "Z"):
        zone_info = UTC
    else:
        try:
            zone_info = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return None
    there = now.astimezone(zone_info)
    day = there.date()
    for offset in (0, 1):
        candidate = datetime.combine(
            day + timedelta(days=offset), datetime.min.time(), tzinfo=zone_info
        ).replace(hour=hour, minute=minute)
        if candidate > there:
            return candidate.astimezone(UTC)
    return None  # pragma: no cover - tomorrow's is always later


class LimitWaiter:
    """``--wait-on-limit HOURS``: a usage limit makes the call wait until the reset (plus :data:`WAIT_MARGIN`; else
    :data:`WAIT_UNKNOWN`) and try again, until ``HOURS`` after the run started. No call is made while waiting."""

    def __init__(
        self, hours: float, *, say: Callable[[str], None] | None = None, local: tzinfo | None = None
    ) -> None:
        if hours <= 0:
            raise ValueError("--wait-on-limit needs a positive number of hours")
        self.until = _now() + timedelta(hours=hours)
        self.say = say or (lambda _message: None)
        self.local = local

    async def wait(self, reset_at: str | None) -> bool:
        """Sleep until the limit resets and return ``True``, or ``False`` when that is past :attr:`until`."""
        now = _now()
        reset = parse_reset(reset_at, now, local=self.local)
        wake = reset + WAIT_MARGIN if reset is not None and reset > now else now + WAIT_UNKNOWN
        if wake > self.until:
            self.say(
                f"usage limit: it resets {reset_at or 'at a time the CLI did not name'}, after --wait-on-limit's end "
                f"({self.until:%Y-%m-%d %H:%M} UTC): stopping — run the same command again later, it resumes"
            )
            return False
        self.say(f"usage limit: waiting until {wake:%Y-%m-%d %H:%M} UTC (no call is made while waiting)")
        await _sleep((wake - now).total_seconds())
        return True


def outcome_of(exc: BaseException) -> str:
    """The ledger's word for a failed call."""
    kinds: tuple[tuple[type[BaseException], str], ...] = (
        (ClaudeRateLimited, "rate_limited"),
        (ClaudeBadOutput, "bad_output"),
        (ClaudeTimeout, "timeout"),
        (ClaudeAuthError, "auth"),
        (ClaudeNotInstalled, "not_installed"),
    )
    return next((word for kind, word in kinds if isinstance(exc, kind)), "error")


class Ledger:
    """``ledger.jsonl``: one line per live call — when, which recording (purpose, key, letters, run), how it went,
    what it cost, how long it took, the model that answered and the ``claude`` that was asked. No prompt, no
    answer. Committed with the recordings it made."""

    def __init__(self, path: Path, *, repeat: int = 1) -> None:
        self.path = Path(path)
        self.repeat = repeat
        self.cli_version: str | None = None

    def write(
        self, req: LLMRequest, *, outcome: str, started: float, response: LLMResponse | None = None
    ) -> None:
        usage = response.usage if response is not None else None
        line = {
            "at": _now().replace(microsecond=0).isoformat(),
            "purpose": req.purpose,
            "key": request_key(req)[:24],
            "docs": list(req.doc_ids),
            "repeat": self.repeat,
            "outcome": outcome,
            "cost_usd": usage.cost_usd if usage is not None else 0.0,
            "duration_ms": usage.duration_ms if usage is not None else 0,
            "wall_ms": round((time.monotonic() - started) * 1000),
            "served_model": (response.model or None) if response is not None else None,
            "cli_version": self.cli_version,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(line, sort_keys=True) + "\n")


def ledger_spent(paths: Sequence[Path], *, docs: Collection[str] | None, repeat: int) -> float:
    """What the ledgers say was spent on these letters at this repeat: the lines with ``repeat`` whose ``docs`` name
    one of ``docs`` (``None``: every line at that repeat, for a ledger that holds one set, as Ask's). A recording step
    is one split (or set) at one repeat, so this is what the step spent so far, over every earlier run and resume."""
    wanted = None if docs is None else set(docs)
    total = 0.0
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if int(row.get("repeat") or 1) != repeat:
                continue
            if wanted is not None and not wanted.intersection(row.get("docs") or []):
                continue
            total += float(row.get("cost_usd") or 0.0)
    return total


def _rate_limited(text: str | None) -> bool:
    lowered = (text or "").lower()
    return "usage limit" in lowered or "rate limit" in lowered


class LiveCalls:
    """Wraps the live ``claude``: the budget stop, waiting through a usage limit, and a ledger line per call."""

    def __init__(
        self,
        inner: LLMBackend,
        *,
        ledger: Ledger | None = None,
        budget: Budget | None = None,
        waiter: LimitWaiter | None = None,
    ) -> None:
        self.inner = inner
        self.ledger = ledger
        self.budget = budget
        self.waiter = waiter
        self.name = inner.name

    def _log(
        self, req: LLMRequest, outcome: str, started: float, response: LLMResponse | None = None
    ) -> None:
        if self.ledger is not None:
            self.ledger.write(req, outcome=outcome, started=started, response=response)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        while True:
            if self.budget is not None:
                self.budget.check()
            started = time.monotonic()
            try:
                response = await self.inner.complete(req)
            except ClaudeRateLimited as exc:
                self._log(req, "rate_limited", started)
                if self.waiter is not None and await self.waiter.wait(exc.reset_at):
                    continue
                raise
            except LLMError as exc:
                self._log(req, outcome_of(exc), started)
                raise
            if self.budget is not None:
                self.budget.add(response.usage.cost_usd)
            self._log(req, "ok", started, response)
            return response

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        """As :meth:`complete`, for a streamed call (Ask's): the CLI backend yields its errors as events, so a usage
        limit is an error event before anything else (its reset time is not passed on: the wait is 30 minutes)."""
        while True:
            if self.budget is not None and self.budget.reached:
                yield StreamEvent(type="error", error=self.budget.message())
                return
            started = time.monotonic()
            limited: StreamEvent | None = None
            first = True
            events = self.inner.stream(req)
            try:
                async for event in events:
                    if first and event.type == "error" and _rate_limited(event.error):
                        limited = event
                        break
                    first = False
                    if event.type == "done" and event.response is not None:
                        if self.budget is not None:
                            self.budget.add(event.response.usage.cost_usd)
                        self._log(req, "ok", started, event.response)
                    elif event.type == "error":
                        self._log(req, "error", started)
                    yield event
            finally:
                close = getattr(events, "aclose", None)
                if close is not None:
                    await close()
            if limited is None:
                return
            self._log(req, "rate_limited", started)
            if self.waiter is not None and await self.waiter.wait(None):
                continue
            yield limited
            return


async def claude_version(binary: str | None = None) -> str | None:
    """``claude --version`` (zero tokens; no model is asked)."""
    return await claude_cli.version(binary)


@dataclass
class LiveSetup:
    """What a live run's stacks share: the budget, the waiting, the ``claude`` asked, its version, the ledgers, and
    the provenance each new cassette is stamped with."""

    repeat: int = 1
    budget: Budget | None = None
    waiter: LimitWaiter | None = None
    cli: Any = None
    cli_version: str | None = None
    ledgers: list[Ledger] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    async def resolve_version(self) -> None:
        """Ask the live ``claude`` for its version once (a stand-in without a ``binary`` has none)."""
        binary = getattr(self.cli, "binary", None)
        if self.cli_version is None and isinstance(binary, str) and binary:
            self.cli_version = await claude_version(binary)
        for ledger in self.ledgers:
            ledger.cli_version = self.cli_version
        self.provenance["cli_version"] = self.cli_version


# --------------------------------------------------------------------------------------------------
# One recorder at a time
# --------------------------------------------------------------------------------------------------


class RecorderBusy(RuntimeError):
    """Another recording holds the recorder lock (or a dead one left it)."""


def pid_alive(pid: int) -> bool:
    """Whether process ``pid`` runs on this computer (a probe: no signal is sent)."""
    if os.name == "nt":  # pragma: no cover - os.kill would end it there; recordings run on Linux and macOS
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_lock(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _holder_alive(holder: Mapping[str, Any]) -> bool:
    if holder.get("host") != HOST:
        return True  # another computer's: we can't tell
    pid = holder.get("pid")
    return isinstance(pid, int) and pid_alive(pid)


class RecorderLock:
    """Holds ``path`` (pid, host, start, command) for one recording; a second recorder is refused."""

    def __init__(self, path: Path, *, command: str) -> None:
        self.path = Path(path)
        self.command = command
        self.held = False

    def __enter__(self) -> RecorderLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def acquire(self) -> None:
        payload = {
            "pid": os.getpid(),
            "host": HOST,
            "started": _now().replace(microsecond=0).isoformat(),
            "command": self.command,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise RecorderBusy(_busy(self.path, read_lock(self.path))) from None
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump(payload, out)
        self.held = True

    def release(self) -> None:
        if not self.held:
            return
        holder = read_lock(self.path)
        if holder is not None and holder.get("pid") == os.getpid() and holder.get("host") == HOST:
            self.path.unlink(missing_ok=True)
        self.held = False


def _busy(path: Path, holder: Mapping[str, Any] | None) -> str:
    if holder is None:
        return f"{path} exists but cannot be read: if no recording runs, free it with `python -m evals.harness unlock`"
    who = f"pid {holder.get('pid')} on {holder.get('host')}, since {holder.get('started')}: {holder.get('command')}"
    if _holder_alive(holder):
        return f"another recording is running ({who}) — one recorder at a time; wait for it to finish"
    return (
        f"a recording lock remains from a recorder that is no longer running ({who}): check what it recorded, then "
        "free it with `python -m evals.harness unlock`"
    )


def unlock(path: Path) -> tuple[int, str]:
    """Free the recorder lock at ``path`` if its recorder is no longer running: ``(exit code, what happened)``."""
    if not path.exists():
        return 0, f"no recording lock at {path}"
    holder = read_lock(path)
    if holder is not None and _holder_alive(holder):
        return 1, f"not freed: {_busy(path, holder)}"
    path.unlink(missing_ok=True)
    who = f"pid {holder.get('pid')}" if holder is not None else "an unreadable lock"
    return 0, f"freed the recording lock of {who} (no longer running)"


# --------------------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------------------


def dirty_paths(root: Path = ROOT) -> list[str] | None:
    """The code paths (under ``src/`` and ``evals/``, not results or recordings) that differ from the commit, or
    ``None`` without git."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "src", "evals"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    paths = []
    for line in result.stdout.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path and not path.startswith(("evals/results/", "evals/recorded/")):
            paths.append(path)
    return sorted(paths)


# --------------------------------------------------------------------------------------------------
# Capturing the requests a replay makes (lock-requests, diff-requests)
# --------------------------------------------------------------------------------------------------


class _Capture:
    """Logs the lock entry of every request made through it (built while its attachments exist)."""

    def __init__(self, inner: LLMBackend) -> None:
        self.inner = inner
        self.name = inner.name
        self.entries: dict[str, dict[str, Any]] = {}

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.entries[lock_key(req)] = lock_entry(req)
        return await self.inner.complete(req)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.entries[lock_key(req)] = lock_entry(req)
        async for event in self.inner.stream(req):
            yield event


def capture_requests(
    recorded_dir: Path = RECORDED_DIR,
    *,
    model: str = DEFAULT_MODEL,
    splits: Sequence[str] | None = None,
    ids: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Replay every recorded split (or ``splits``; or the letters ``ids``) with every condition and return the lock
    entry of each request made. Fails when a prediction errs (a missing recording, say)."""
    from evals import run as eval_run
    from evals import splits as registry
    from evals.conditions import ordnung_prompt_hashes
    from evals.records import load_manifest

    manifest = load_manifest(eval_run.MANIFEST_PATH)
    allowed = {entry.id for entry in manifest}
    wanted = set(ids or ())
    names = list(splits or registry.recorded())
    if wanted:
        names = [name for name in names if any(e.split == name and e.id in wanted for e in manifest)]
    stale = eval_run.stale_prompts(recorded_dir / eval_run.safe_name(model), ordnung_prompt_hashes())
    if stale:
        raise HarnessError(f"the prompts changed since the recordings were made: {', '.join(stale)}")
    entries: dict[str, dict[str, Any]] = {}
    for name in names:
        selected = sorted(e.id for e in manifest if e.split == name and e.id in wanted) if wanted else None
        config = eval_run.RunConfig(
            split=name,
            models=[model],
            ids=selected,
            recorded_dir=recorded_dir,
            write_docs=False,
            write_results=False,
            resamples=10,
            check_requests=False,
            run_date="2026-01-01",
        )
        capture = _Capture(eval_run.make_backend(config, model, allowed))
        outcome = asyncio.run(eval_run.run_benchmark(config, backend=capture))
        errors = [p for run in outcome.runs for p in run.errors]
        if errors or not outcome.ok:
            first = errors[0] if errors else None
            detail = f"{first.condition} {first.entry_id}: {first.error}" if first else "stopped"
            raise HarnessError(f"{name}: {len(errors)} prediction(s) failed to replay — {detail}")
        entries.update(capture.entries)
    return entries


def capture_ask_requests(
    recorded_dir: Path = ASK_RECORDED_DIR, *, model: str = DEFAULT_MODEL, only: Sequence[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Replay the Ask benchmark and return the lock entry of each turn's request."""
    from evals.ask import run as ask_run

    original = ask_run.make_backend
    captures: list[_Capture] = []

    def capturing(*args: Any, **kwargs: Any) -> LLMBackend:
        capture = _Capture(original(*args, **kwargs))
        captures.append(capture)
        return capture

    ask_run.make_backend = capturing
    try:
        result = ask_run.run(
            ask_run.Config(model=model, recorded_dir=recorded_dir, only=list(only) if only else None)
        )
    finally:
        ask_run.make_backend = original
    if result.misses:
        raise HarnessError(f"{len(result.misses)} Ask turn(s) have no recording")
    entries: dict[str, dict[str, Any]] = {}
    for capture in captures:
        entries.update(capture.entries)
    return entries


@dataclass
class LockDiff:
    """How the requests made now differ from a lock."""

    changed: dict[str, list[str]]
    new: list[str]
    missing: list[str]
    docs: dict[str, list[str]] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not (self.changed or self.new or self.missing)

    def lines(self, *, limit: int = 20) -> list[str]:
        if self.clean:
            return ["no request changed: every request made matches its locked entry"]
        out: list[str] = []
        if self.changed:
            out.append(
                f"{len(self.changed)} request(s) changed under the same key (a replay would serve answers to the old "
                "request), by purpose and part:"
            )
            by_purpose: dict[str, Counter[str]] = {}
            for key, fields in self.changed.items():
                by_purpose.setdefault(key.split("/")[0], Counter()).update(fields)
            for purpose, counts in sorted(by_purpose.items()):
                out.append(f"  {purpose}: " + ", ".join(f"{name} {n}" for name, n in sorted(counts.items())))
            for key in sorted(self.changed)[:limit]:
                out.append(f"    {key} {', '.join(self.docs.get(key, []))}: {', '.join(self.changed[key])}")
        if self.new:
            out.append(
                f"{len(self.new)} request(s) not in the lock (a key changed, or never recorded): record them"
            )
            out += [f"    {key} {', '.join(self.docs.get(key, []))}" for key in sorted(self.new)[:limit]]
        if self.missing:
            out.append(
                f"{len(self.missing)} locked request(s) no longer made (a key changed, or a letter left)"
            )
            out += [f"    {key}" for key in sorted(self.missing)[:limit]]
        return out


def diff_locks(
    old: Mapping[str, Mapping[str, Any]], new: Mapping[str, Mapping[str, Any]], *, complete: bool = True
) -> LockDiff:
    """Compare the entries of requests made now (``new``) with a lock (``old``). ``complete``: ``new`` covers every
    recorded request, so a run-1 entry of ``old`` that is not in it is no longer made (repeats are never)."""
    changed: dict[str, list[str]] = {}
    fresh: list[str] = []
    for key, entry in new.items():
        known = old.get(key)
        if known is None:
            fresh.append(key)
        elif known.get("content") != entry.get("content"):
            was, now = entry_fields(known), entry_fields(entry)
            changed[key] = sorted(name for name in set(was) | set(now) if was.get(name) != now.get(name))
    missing = (
        sorted(key for key, entry in old.items() if key not in new and "repeat" not in entry)
        if complete
        else []
    )
    docs = {key: list(entry.get("docs") or []) for key, entry in {**old, **new}.items()}
    return LockDiff(changed=changed, new=sorted(fresh), missing=missing, docs=docs)


def _lock_at(ref: str, path: Path) -> str:
    """The lock file at ``path`` as it is in commit ``ref`` (``git show``)."""
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise HarnessError(f"no {relative} at {ref}: {result.stderr.strip()[:300]}")
    return result.stdout


# --------------------------------------------------------------------------------------------------
# The ledger, summed
# --------------------------------------------------------------------------------------------------


def ledger_summary(paths: Sequence[Path], *, since: str | None = None) -> list[str]:
    """What the ledgers say a recording cost (calls by outcome, dollars, first and last call)."""
    lines: list[str] = []
    for path in paths:
        rows = []
        if path.exists():
            rows = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
        rows = [row for row in rows if since is None or str(row.get("at", "")) >= since]
        if not rows:
            lines.append(f"{path}: no call")
            continue
        outcomes = Counter(str(row.get("outcome")) for row in rows)
        cost = sum(float(row.get("cost_usd") or 0.0) for row in rows)
        times = sorted(str(row.get("at")) for row in rows)
        versions = sorted({str(row.get("cli_version")) for row in rows})
        lines.append(
            f"{path}: {len(rows)} call(s) ({', '.join(f'{k} {v}' for k, v in sorted(outcomes.items()))}), "
            f"${cost:.4f}, from {times[0]} to {times[-1]}, claude {', '.join(versions)}"
        )
    return lines


# --------------------------------------------------------------------------------------------------
# The live smoke
# --------------------------------------------------------------------------------------------------


def _python_args(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def _child(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False, timeout=3 * 3600)


def _cassettes(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.json") if path.parent != root)


def _answer(path: Path) -> Any:
    if not path.is_file():
        return None
    recorded = json.loads(path.read_text(encoding="utf-8"))
    if "error" in recorded:  # a recorded model failure
        return {"failure": recorded["error"]}
    response = recorded.get("response") or {}
    return response.get("data") if response.get("data") is not None else response.get("text")


def _recording(root: Path, key: str) -> Path:
    path = root / f"{key}.json"
    return path if path.is_file() else root / f"{key}.failure.json"


def smoke_checks(scratch_root: Path, committed_root: Path, *, cap: float) -> dict[str, Any]:
    """Compare a repeat recorded into ``scratch_root`` with run 1's recordings in ``committed_root``.

    A repeat's first request of each letter and condition is run 1's request under a key of its own: it must be
    byte for byte the same request (``requests_identical_to_run_1``). Its follow-ups (a repair, a re-ask) depend on
    the answers, so some may be calls run 1 never made; they are counted, not judged."""
    lock = RequestLock(scratch_root / LOCK_FILE).entries
    committed = RequestLock(committed_root / LOCK_FILE).entries
    cassettes = _cassettes(scratch_root)
    ledger_path = scratch_root / LEDGER_FILE
    ledger = (
        [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
        if ledger_path.exists()
        else []
    )
    repeated = {key: entry for key, entry in lock.items() if entry.get("of") in committed}
    costs = [float(row.get("cost_usd") or 0.0) for row in ledger]
    answers = [
        (_answer(_recording(scratch_root, key)), _answer(_recording(committed_root, str(entry["of"]))))
        for key, entry in repeated.items()
    ]
    return {
        "calls": len(ledger),
        "cassettes": len(cassettes),
        "locked": len(lock),
        "keys_differ_from_run_1": bool(lock) and not set(lock) & set(committed),
        "repeated": len(repeated),
        "follow_ups_run_1_did_not_make": len(lock) - len(repeated),
        "requests_identical_to_run_1": bool(repeated)
        and all(
            committed[str(entry["of"])].get("content") == entry.get("content") for entry in repeated.values()
        ),
        "one_ledger_line_per_call": len(ledger) == len(cassettes) == len(lock),
        "spent_usd": round(sum(costs), 4),
        # the cap stops new calls: the calls already under way may pass it by one call each
        "within_budget": sum(costs) <= cap + max(costs, default=0.0),
        "answers_compared": len(answers),
        "answers_that_differ_from_run_1": sum(1 for mine, first in answers if mine != first),
    }


def smoke_ok(report: Mapping[str, Any], *, ids: Sequence[str], ask_only: Sequence[str]) -> bool:
    """Whether the smoke passed: the lock and the budget stop, the benchmark's repeat; and, when Ask turns were asked
    for, Ask's too (it ran, each turn once, under keys of its own with run 1's request, one ledger line per call)."""
    checks = report["benchmark"]
    benchmark = bool(
        report["recorder_lock_refuses_a_second_recording"]
        and report["zero_budget_stops_before_any_call"]
        and report["recording_exit"] == 0
        and checks["keys_differ_from_run_1"]
        and checks["repeated"] >= len(ids)
        and checks["requests_identical_to_run_1"]
        and checks["one_ledger_line_per_call"]
        and checks["within_budget"]
    )
    if not ask_only:
        return benchmark
    ask = report.get("ask")
    return bool(
        benchmark
        and isinstance(ask, Mapping)
        and report.get("ask_exit") == 0
        and ask["calls"] == len(ask_only)
        and ask["repeated"] >= len(ask_only)
        and ask["keys_differ_from_run_1"]
        and ask["requests_identical_to_run_1"]
        and ask["one_ledger_line_per_call"]
        and ask["within_budget"]
    )


def run_smoke(
    scratch: Path,
    *,
    ids: Sequence[str] = SMOKE_IDS,
    conditions: Sequence[str] | None = None,
    ask_only: Sequence[str] = (),
    cap: float = 1.0,
    recorder_lock: Path = RECORDER_LOCK,
) -> dict[str, Any]:
    """The live smoke before a paid recording. It calls the model through ``ORDNUNG_CLAUDE_BIN`` (about $0.6) and
    records into ``scratch``, which is thrown away afterwards.

    1. While this process holds the recorder lock, a second ``--live`` run is refused (no call).
    2. ``--max-cost-usd 0`` starts no call.
    3. ``ids`` × every condition (or ``conditions``) at ``--repeat 2``, into ``scratch``: :func:`smoke_checks`
       against run 1's recordings and request lock.
    4. The Ask turns ``ask_only`` the same way, once ``evals.ask`` takes ``--repeat``.

    If every repeated answer equals run 1's, the report says so: repeats would measure nothing new."""
    from evals.run import safe_name

    if scratch.exists() and any(scratch.iterdir()):
        raise HarnessError(f"{scratch} is not empty: the smoke records into a fresh folder")
    scratch.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"scratch": str(scratch), "ids": list(ids), "conditions": list(conditions or [])}
    base = ["--split", "dev", "--no-docs", "--quiet", "--date", _now().date().isoformat()]
    base += ["--recorder-lock", str(recorder_lock)]
    only = ["--conditions", *conditions] if conditions else []

    # 1. one recorder at a time: a second recording is refused while this one holds the lock (no call)
    with RecorderLock(recorder_lock, command="python -m evals.harness smoke"):
        refused = _child(
            _python_args(
                "evals.run", "--live", *base, "--ids", ids[0], "--recorded-dir", str(scratch / "busy")
            )
        )
    report["recorder_lock_refuses_a_second_recording"] = (
        refused.returncode != 0 and "another recording is running" in refused.stderr
    )

    # 2. the budget stop: a zero budget starts no call
    zero = scratch / "zero"
    stopped = _child(
        _python_args(
            "evals.run", "--live", *base, "--ids", ids[0], "--conditions", "llm_only", "--repeat", "2",
            "--recorded-dir", str(zero), "--results-dir", str(zero / "results"), "--max-cost-usd", "0",
        )
    )  # fmt: skip
    zero_root = zero / safe_name(DEFAULT_MODEL)
    report["zero_budget_stops_before_any_call"] = (
        stopped.returncode != 0 and "budget reached" in stopped.stderr and not _cassettes(zero_root)
        and not (zero_root / LEDGER_FILE).exists()
    )  # fmt: skip

    # 3. the repeat: the letters, every condition, run 2
    recorded = scratch / "recorded"
    run = _child(
        _python_args(
            "evals.run", "--live", *base, *only, "--ids", *ids, "--repeat", "2", "--concurrency", "2",
            "--recorded-dir", str(recorded), "--results-dir", str(scratch / "results"), "--max-cost-usd", f"{cap:g}",
        )
    )  # fmt: skip
    report["recording_exit"] = run.returncode
    report["recording_stderr_tail"] = run.stderr.strip().splitlines()[-5:]
    root = recorded / safe_name(DEFAULT_MODEL)
    report["benchmark"] = smoke_checks(root, RECORDED_DIR / safe_name(DEFAULT_MODEL), cap=cap)

    # 4. Ask, once its runner takes --repeat (the same wrappers)
    helped = _child(_python_args("evals.ask", "--help")) if ask_only else None
    if helped is not None and "--repeat" in helped.stdout:
        ask_dir = scratch / "ask"
        asked = _child(
            _python_args(
                "evals.ask", "--live", "--repeat", "2", "--only", ",".join(ask_only), "--recorded-dir", str(ask_dir),
                "--recorder-lock", str(recorder_lock), "--concurrency", "1", "--max-cost-usd", "0.3",
            )
        )  # fmt: skip
        report["ask_exit"] = asked.returncode
        report["ask_stderr_tail"] = asked.stderr.strip().splitlines()[-5:]
        report["ask"] = smoke_checks(
            ask_dir / safe_name(DEFAULT_MODEL), ASK_RECORDED_DIR / safe_name(DEFAULT_MODEL), cap=0.3
        )
    else:
        report["ask"] = "not run: evals.ask takes no --repeat yet" if ask_only else "not asked"
    checks = report["benchmark"]
    report["ok"] = smoke_ok(report, ids=ids, ask_only=ask_only)
    if checks["answers_compared"] and not checks["answers_that_differ_from_run_1"]:
        report["note"] = (
            "every repeated answer equals run 1's: repeats measure nothing new, so the pre-registration drops the "
            "stability family F3 and says why"
        )
    (scratch / "smoke.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return report


# --------------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.harness", description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    commands = parser.add_subparsers(dest="command", required=True)

    unlock_cmd = commands.add_parser(
        "unlock", help="free the recorder lock of a recorder that is no longer running"
    )
    unlock_cmd.add_argument("--lock", type=Path, default=RECORDER_LOCK, help=argparse.SUPPRESS)

    for name, help_text in (
        (
            "lock-requests",
            "replay and compare every request with the lock (--check), or write the entries (--write)",
        ),
        ("diff-requests", "which requests changed since the lock at REF, and in which part"),
    ):
        command = commands.add_parser(name, help=help_text)
        if name == "diff-requests":
            command.add_argument(
                "ref", nargs="?", default="HEAD", help="the commit whose lock to compare with"
            )
        else:
            mode = command.add_mutually_exclusive_group()
            mode.add_argument("--check", action="store_true", help="compare (the default)")
            mode.add_argument("--write", action="store_true", help="write the captured entries into the lock")
        command.add_argument("--ask", action="store_true", help="the Ask benchmark's requests")
        command.add_argument("--recorded-dir", type=Path, default=None, help="recordings root")
        command.add_argument("--model", default=DEFAULT_MODEL)
        command.add_argument("--split", nargs="+", dest="splits", help="only these splits")
        command.add_argument("--ids", nargs="+", help="only these letters (or, with --ask, question ids)")

    ledger_cmd = commands.add_parser("ledger", help="what a recording cost, from its ledger")
    ledger_cmd.add_argument("files", nargs="*", type=Path)
    ledger_cmd.add_argument("--since", help="only calls at or after this ISO time")

    smoke = commands.add_parser(
        "smoke", help="the live smoke before a paid recording (calls the model: about $0.6)"
    )
    smoke.add_argument("--scratch", type=Path, required=True, help="a fresh folder; thrown away afterwards")
    smoke.add_argument("--ids", nargs="+", default=list(SMOKE_IDS))
    smoke.add_argument("--conditions", nargs="+", help="only these conditions (default: all four)")
    smoke.add_argument("--ask-only", default="", help="comma-separated Ask question ids (three)")
    smoke.add_argument("--max-cost-usd", type=float, default=1.0)
    smoke.add_argument("--recorder-lock", type=Path, default=RECORDER_LOCK, help=argparse.SUPPRESS)
    return parser


def _capture(args: argparse.Namespace) -> tuple[dict[str, dict[str, Any]], Path, bool]:
    if args.ask:
        root_dir = args.recorded_dir or ASK_RECORDED_DIR
        entries = capture_ask_requests(root_dir, model=args.model, only=args.ids)
        complete = not args.ids
    else:
        root_dir = args.recorded_dir or RECORDED_DIR
        entries = capture_requests(root_dir, model=args.model, splits=args.splits, ids=args.ids)
        complete = not (args.ids or args.splits)
    return entries, lock_path(root_dir, args.model), complete


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "unlock":
            code, message = unlock(args.lock)
            print(message)
            return code
        if args.command == "ledger":
            files = list(args.files) or [
                lock_path(RECORDED_DIR).with_name(LEDGER_FILE),
                lock_path(ASK_RECORDED_DIR).with_name(LEDGER_FILE),
            ]
            for line in ledger_summary(files, since=args.since):
                print(line)
            return 0
        if args.command == "smoke":
            only = [part.strip() for part in args.ask_only.split(",") if part.strip()]
            report = run_smoke(
                args.scratch,
                ids=args.ids,
                conditions=args.conditions,
                ask_only=only,
                cap=args.max_cost_usd,
                recorder_lock=args.recorder_lock,
            )
            print(json.dumps(report, indent=1, sort_keys=True))
            return 0 if report["ok"] else 1
        entries, path, complete = _capture(args)
        if args.command == "diff-requests":
            old = json.loads(_lock_at(args.ref, path))
            diff = diff_locks(old, entries, complete=complete)
            print(f"requests made now vs {path.name} at {args.ref} ({len(entries)} request(s)):")
        else:
            lock = RequestLock(path)
            if args.write:
                for key, entry in entries.items():
                    lock.entries[key] = entry
                lock.save()
                print(
                    f"wrote {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} into {path} ({len(lock.entries)} in all)"
                )
                return 0
            diff = diff_locks(lock.entries, entries, complete=False)
            print(f"requests made now vs {path} ({len(entries)} request(s)):")
        for line in diff.lines():
            print(line)
        return 0 if not (diff.changed or diff.new) else 1
    except (HarnessError, RecorderBusy) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
