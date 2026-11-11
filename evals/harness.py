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
* ``retake --split S --repeat N --ids … --to DIR`` (or ``--whole-run --recorded-dir D`` for an Ask run or a stress
  invocation) — move an incomplete unit's recordings aside and free their lock entries, so it is recorded again whole
  on its new day; it lists each recording's sha256, outcome and cost. ``--invalid ID`` moves every unit of a read a
  recorded deviation made invalid (never-waivable, or the runner-defect rule), so the read is recorded again;
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
from collections.abc import AsyncIterator, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
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


def utc_today() -> date:
    """The day a recording takes as its today: the UTC date now (at the start of a run, the day the ``claude`` CLI
    tells the model in its own context, beside the today Ordnung gives it)."""
    return _now().date()


def check_recording_day(simulated: Iterable[str | date], day: date, *, allow: bool = False) -> None:
    """Refuse a recording whose simulated today is not ``day``, the day it is recorded: the CLI tells the model the
    machine's date as well, its date override does not work in ``-p`` mode, so a ledger or letter pinned to another
    day shows the model two todays (the development set's Ask recording of 30 Oct 2026, pinned to 28 Sep, had
    answers call open deadlines passed). Build the letters or the ledger for the day instead. ``allow``
    (``--allow-another-today``, where :func:`check_another_today` lets it): a development set re-recorded in the open,
    or a smoke into a scratch folder."""
    days = {value.isoformat() if isinstance(value, date) else str(value) for value in simulated}
    other = sorted(days - {day.isoformat()})
    if other and not allow:
        raise HarnessError(
            f"the simulated today ({', '.join(other)}) is not the day this is recorded ({day.isoformat()}, UTC): the "
            "claude CLI tells the model that day too, so the model would see two todays — build the letters or the "
            "ledger for the recording day; a development set, pinned to its own day, is recorded again with "
            "--allow-another-today, which every new recording and the results disclose (a held-out or final set "
            "takes it only for a smoke into a scratch folder)"
        )


def check_another_today(recorded_dir: Path, *, development: bool) -> None:
    """Where ``--allow-another-today`` may record. A development set (Ask's, the reading benchmark's dev and test
    splits) is pinned to its own today, so recording it again before the freeze — after a change to what Ask's
    tools return, say — is always on another day: the flag records it in the open, into the committed folder too,
    and the cassettes (``recorded_on``) and results (Ask's ``today`` and ``date``, a run's ``simulated_today`` and
    ``recording_day``) say both days. A held-out or final set is built for the day it is recorded; for it the flag
    is only a smoke into a scratch folder outside the checkout, which no results file or index ever reads."""
    if development:
        return
    folder = recorded_dir.resolve()
    if folder.is_relative_to(ROOT.resolve()):
        raise HarnessError(
            f"--allow-another-today records a held-out or final set only into a scratch folder outside the checkout "
            f"(not {folder}): its recording is built for the day it is recorded (--today), never pinned to another"
        )


def recording_provenance(day: date | None, simulated: Iterable[str | date]) -> dict[str, str]:
    """What a live run's new cassettes say about its days: ``recorded_on`` (the UTC day of its start) and, when every
    simulated today is that day, ``today`` too (a disclosed re-recording on another day has none: the request says
    its today)."""
    if day is None:
        return {}
    days = {value.isoformat() if isinstance(value, date) else str(value) for value in simulated}
    return {
        "recorded_on": day.isoformat(),
        **({"today": day.isoformat()} if days == {day.isoformat()} else {}),
    }


class RecordingDayOver(LLMError):
    """The recording's day is over (midnight UTC): a turn recorded on a later day is invalid, so no call starts."""

    def __init__(self, day: date) -> None:
        super().__init__(
            f"the recording day {day.isoformat()} is over (UTC): no call starts on a later day, whose turns would be "
            "invalid — what is recorded is kept; record the rest with letters or a ledger built for the new day"
        )
        self.day = day


# --------------------------------------------------------------------------------------------------
# The final run's units: their window, their day index, stopping at a unit boundary
# --------------------------------------------------------------------------------------------------


def check_window(windows: Iterable[tuple[str, str | None, str | None]], day: date) -> None:
    """Refuse to record a final split's letters on ``day`` unless it is inside each letter's window: ``(id,
    final_day, valid_until)`` from the manifest, the planned day the letters were written for and the last day they
    are valid (every date they score lies after it). A letter whose manifest names no window is never recorded."""
    unbounded = sorted(entry_id for entry_id, first, last in windows if not (first and last))
    if unbounded:
        raise HarnessError(
            f"{', '.join(unbounded[:5])}{' …' if len(unbounded) > 5 else ''}: the manifest names no window (final_day "
            "and valid_until), so these letters are never recorded live"
        )
    outside = sorted(
        {
            (str(first), str(last))
            for _, first, last in windows
            if not (str(first) <= day.isoformat() <= str(last))
        }
    )
    if outside:
        first, last = outside[0]
        raise HarnessError(
            f"{day.isoformat()} is outside the letters' window, {first} to {last}: they were written for those days "
            "and are recorded on no other"
        )


DAY_INDEX_FILE = "final-days.json"


class DayIndex:
    """``final-days.json`` beside a model's recordings: the final splits' units, ``{split: {"r<N>": {entry_id:
    {"day": "YYYY-MM-DD", "cli": "<claude version>"}}}}``. A unit — one letter in one read with all its conditions — is
    written the moment it completes, whole (a temporary file, then a rename): its day is the today it was recorded
    with, so a resume, a replay and the request lock's capture give the letter that day again.

    A unit kept with conditions left unanswered (``--allow-errors``, after the resumes the pre-registration allows) is
    written too, with ``"complete": false`` and ``"unanswered"``: each such condition's failed prediction, as it was
    scored. It keeps its day for every replay, which gives those conditions their recorded failure; it is not
    complete, so a live run still records it (on another day, only after a retake)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise HarnessError(f"{self.path} is not a day index")
            self.data = data

    def attempted(self, split: str, repeat: int) -> dict[str, dict[str, Any]]:
        """Every unit of ``split`` at run ``repeat`` the index names, complete or kept unanswered: entry id → its
        record."""
        return dict(self.data.get(split, {}).get(f"r{repeat}", {}))

    def units(self, split: str, repeat: int) -> dict[str, dict[str, Any]]:
        """The complete units of ``split`` at run ``repeat``: entry id → ``{"day", "cli"}``."""
        return {
            entry_id: unit
            for entry_id, unit in self.attempted(split, repeat).items()
            if unit.get("complete", True)
        }

    def put(
        self,
        split: str,
        repeat: int,
        entry_id: str,
        *,
        day: str,
        cli: str | None,
        unanswered: Mapping[str, Any] | None = None,
    ) -> None:
        """Write a unit: complete, or (``unanswered``: condition → its failed prediction) kept unanswered."""
        unit: dict[str, Any] = {"day": day, "cli": cli}
        if unanswered:
            unit.update(complete=False, unanswered=dict(unanswered))
        self.data.setdefault(split, {}).setdefault(f"r{repeat}", {})[entry_id] = unit
        self._save()

    def remove(self, split: str, repeat: int, entry_ids: Collection[str]) -> list[str]:
        """Take these units out of the index (a retake); the ids that were in it."""
        units = self.data.get(split, {}).get(f"r{repeat}", {})
        gone = sorted(entry_id for entry_id in entry_ids if entry_id in units)
        for entry_id in gone:
            del units[entry_id]
        if gone:
            self._save()
        return gone

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.data, indent=1, sort_keys=True) + "\n"
        write_atomic(self.path, text)


#: ``python -m evals.run``, ``evals.ask`` and ``scripts.eval_perturb`` stopped at a unit boundary (a stop file, or
#: ``--stop-at``): no unit was left half done, and the same command goes on where it stopped.
STOPPED = 4


@dataclass(frozen=True)
class Stop:
    """``--stop-file PATH`` and ``--stop-at HH:MM`` (UTC): before a unit starts, a run checks whether the file exists
    or the clock has passed the time on the day the run started; then no new unit starts, and the units under way
    finish. (``RecordingDayOver`` still forbids any call after midnight.)"""

    file: Path | None = None
    at: datetime | None = None

    @classmethod
    def of(cls, *, file: Path | str | None = None, at: str | None = None) -> Stop | None:
        """The stop for these options (``None`` when neither is given); ``at`` is ``HH:MM`` on today's UTC date."""
        if file is None and at is None:
            return None
        moment = None
        if at is not None:
            match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", at.strip())
            if match is None:
                raise ValueError(f"--stop-at takes a UTC time as HH:MM (00:00 to 23:59), not {at!r}")
            moment = datetime.combine(_now().date(), datetime.min.time(), tzinfo=UTC).replace(
                hour=int(match.group(1)), minute=int(match.group(2))
            )
        return cls(file=Path(file) if file is not None else None, at=moment)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Stop | None:
        return cls.of(file=getattr(args, "stop_file", None), at=getattr(args, "stop_at", None))

    def requested(self) -> str | None:
        """Why no new unit may start, or ``None``."""
        if self.file is not None and self.file.exists():
            return f"the stop file {self.file} exists"
        if self.at is not None and _now() >= self.at:
            return f"it is past --stop-at {self.at:%H:%M} UTC"
        return None


def stopped_message(reason: str) -> str:
    """What a run says when it stopped at a unit boundary."""
    return (
        f"stopped at a unit boundary: {reason} — no new unit started, the units under way finished; run the same "
        f"command again to go on (exit {STOPPED})"
    )


def add_stop_arguments(parser: argparse.ArgumentParser) -> None:
    """``--stop-file`` and ``--stop-at``, as every recorder takes them."""
    parser.add_argument(
        "--stop-file",
        type=Path,
        metavar="PATH",
        help="with --live: start no new unit once this file exists (the units under way finish; exit 4)",
    )
    parser.add_argument(
        "--stop-at",
        metavar="HH:MM",
        help="with --live: start no new unit once the clock passes this time (UTC) on the day the run started "
        "(the units under way finish; exit 4)",
    )


def lock_entries_of(
    lock: RequestLock, *, repeat: int, docs: Collection[str] | None = None
) -> dict[str, dict[str, Any]]:
    """The lock's entries of run ``repeat`` whose letters include one of ``docs`` (``None``: every entry of the
    run)."""
    wanted = None if docs is None else set(docs)
    return {
        key: entry
        for key, entry in lock.entries.items()
        if int(entry.get("repeat") or 1) == repeat
        and (wanted is None or wanted.intersection(entry.get("docs") or []))
    }


def recordings_of(root: Path, key: str) -> list[Path]:
    """The files a lock key's recording may be: the answer, a recorded model failure, an unreadable one set aside."""
    base = root / f"{key}.json"
    candidates = (base, root / f"{key}.failure.json", base.with_name(f"{base.name}.bad"))
    return [path for path in candidates if path.is_file()]


def _ledger_rows(root: Path) -> list[dict[str, Any]]:
    path = root / LEDGER_FILE
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def recorded_day(path: Path, ledger: Sequence[Mapping[str, Any]] = ()) -> str | None:
    """The UTC day a recording was made on: its own provenance (``recorded_on``), else its last ledger line's."""
    try:
        request = json.loads(path.read_text(encoding="utf-8")).get("request") or {}
    except (OSError, ValueError, AttributeError):
        request = {}
    day = request.get("recorded_on") if isinstance(request, dict) else None
    if isinstance(day, str) and day:
        return day
    key = f"{path.parent.name}/{path.name.split('.', 1)[0]}"
    times = [str(row.get("at") or "") for row in ledger if f"{row.get('purpose')}/{row.get('key')}" == key]
    latest: str = max(times, default="")
    return latest[:10] or None


def units_of_another_day(
    root: Path, entry_ids: Collection[str], *, repeat: int, day: date
) -> dict[str, list[Path]]:
    """The incomplete units among ``entry_ids`` that have recordings made on another day than ``day`` (or on a day
    that cannot be told): entry id → those recordings. Such a unit cannot go on today (its recorded turns told the
    model another today); it is retaken whole (:func:`retake`)."""
    lock = RequestLock(root / LOCK_FILE)
    ledger = _ledger_rows(root)
    found: dict[str, list[Path]] = {}
    for key, entry in lock_entries_of(lock, repeat=repeat, docs=entry_ids).items():
        for path in recordings_of(root, key):
            if recorded_day(path, ledger) != day.isoformat():
                for entry_id in set(entry.get("docs") or []) & set(entry_ids):
                    found.setdefault(entry_id, []).append(path)
    return {entry_id: sorted(paths) for entry_id, paths in sorted(found.items())}


def recordings_of_another_day(root: Path, *, repeat: int, day: date) -> dict[Path, str | None]:
    """The recordings of run ``repeat`` in ``root`` (by its request lock) made on another day than ``day``, each with
    the day it was made on (``None``: a day that cannot be told). An Ask run or a stress invocation is one unit: with
    any such recording it cannot go on today (its recorded turns told the model another today), and it is retaken
    whole (:func:`retake` with ``whole_run``), which moves the same recordings."""
    ledger = _ledger_rows(root)
    days = {
        path: recorded_day(path, ledger)
        for key in lock_entries_of(RequestLock(root / LOCK_FILE), repeat=repeat)
        for path in recordings_of(root, key)
    }
    return {path: made for path, made in sorted(days.items()) if made != day.isoformat()}


class UnitClosed(LLMError):
    """A call for a unit that is already complete: its recordings answer every call it makes, so a call that reaches
    the model would record a valid answer again."""


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


_INTERPRETER = re.compile(r"(?i)^\.?(?:python|pypy)[\w.+-]*?(?:\.exe)?$")
"""An interpreter's file name: ``python``, ``python3.11``, ``python.exe``, ``pythonw.exe``, ``pypy3``, a Nix
wrapper's ``.python3.11-wrapped``."""


def _is_interpreter(command: Any, args: Any) -> bool:
    """Whether an MCP server's ``command`` is the Python that starts it: it runs a module (``<command> -m …``, as
    every server Ordnung starts does, with ``sys.executable``), or its file name is an interpreter's — on any
    system's separators, so a lock made on Windows reads the same on Linux."""
    if not isinstance(command, str):
        return False
    runs_module = isinstance(args, list) and bool(args) and args[0] == "-m"
    return runs_module or bool(_INTERPRETER.match(re.split(r"[\\/]", command)[-1]))


def normalized_mcp(config: Mapping[str, Any] | None) -> Any:
    """The MCP config as far as the model can tell: the interpreter that starts a server (``sys.executable``, a
    path of the machine and its venv, in no replay key) and the data folder Ask's server reads (a fresh temporary
    folder each run) are placeholders; the server, its arguments and its environment stay. Another program's
    command (``npx``, say) is kept: a change to it is a change to the request."""

    def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            out = {k: walk(v) for k, v in value.items()}
            if _is_interpreter(value.get("command"), value.get("args")):
                out["command"] = "<python>"
            return out
        if isinstance(value, list):
            items: list[Any] = []
            for item in value:
                items.append("<data-dir>" if items and items[-1] == "--data-dir" else walk(item))
            return items
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
    what this step already spent (:func:`ledger_spent`), so resuming with the same command gets no new cap.
    ``refused`` counts the calls it kept from starting: a run whose last call reached the cap refused none, and asked
    everything; one that refused a call was cut."""

    def __init__(self, cap: float, *, spent: float = 0.0) -> None:
        if cap < 0:
            raise ValueError("a budget is not negative")
        self.cap = cap
        self.spent = max(0.0, spent)
        self.refused = 0

    @property
    def reached(self) -> bool:
        return self.spent >= self.cap

    def message(self) -> str:
        return (
            f"budget reached: ${self.spent:.4f} spent of --max-cost-usd {self.cap:g} (counting this step's earlier "
            "calls in its ledger); what is recorded is kept — resume with a higher --max-cost-usd"
        )

    def refuse(self) -> str:
        """Keep a call from starting: count it, and say why (:meth:`message`)."""
        self.refused += 1
        return self.message()

    def check(self) -> None:
        if self.reached:
            raise BudgetReached(self.refuse())

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


#: Why :class:`LiveCalls` returned a call without an answer for a reason of the whole run, not of the call
#: (:attr:`LiveCalls.unasked`): ``--max-cost-usd`` refused it, a usage limit was met and not waited out (no
#: ``--wait-on-limit``, or a reset after its end), or the recording day is over (midnight UTC). An Ask run is one unit:
#: one with such a call was cut, and ``evals.ask`` writes no results file for it.
UNASKED_BUDGET = "budget"
UNASKED_LIMIT = "usage limit"
UNASKED_DAY_OVER = "day over"


class LiveCalls:
    """Wraps the live ``claude``: the budget stop, waiting through a usage limit, a ledger line per call, (``day``)
    no call once the recording's day is over (:class:`RecordingDayOver`), and (``closed``) no call for a letter whose
    unit is already complete (:class:`UnitClosed`). ``unasked`` counts, by reason (:data:`UNASKED_BUDGET`,
    :data:`UNASKED_LIMIT`, :data:`UNASKED_DAY_OVER`), the calls it returned without an answer for a reason of the run:
    what a runner reads to tell a run they cut from a whole one, whatever the cause."""

    def __init__(
        self,
        inner: LLMBackend,
        *,
        ledger: Ledger | None = None,
        budget: Budget | None = None,
        waiter: LimitWaiter | None = None,
        day: date | None = None,
        closed: Collection[str] = (),
        unasked: Counter[str] | None = None,
    ) -> None:
        self.inner = inner
        self.ledger = ledger
        self.budget = budget
        self.waiter = waiter
        self.day = day
        self.closed = frozenset(closed)
        self.unasked: Counter[str] = unasked if unasked is not None else Counter()
        self.name = inner.name

    def _day_over(self) -> RecordingDayOver | None:
        return RecordingDayOver(self.day) if self.day is not None and utc_today() != self.day else None

    def _refused(self, req: LLMRequest) -> UnitClosed | None:
        done = sorted(self.closed.intersection(req.doc_ids))
        if not done:
            return None
        return UnitClosed(
            f"{req.purpose} for {', '.join(done)}: its unit is complete, so its recordings answer every call it makes "
            "— this one reached the model, which would record a valid answer again on another day; check its "
            "recordings with a replay"
        )

    def _log(
        self, req: LLMRequest, outcome: str, started: float, response: LLMResponse | None = None
    ) -> None:
        if self.ledger is not None:
            self.ledger.write(req, outcome=outcome, started=started, response=response)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if (refused := self._refused(req)) is not None:
            raise refused
        while True:
            if self.budget is not None:
                try:
                    self.budget.check()
                except BudgetReached:
                    self.unasked[UNASKED_BUDGET] += 1
                    raise
            if (over := self._day_over()) is not None:
                self.unasked[UNASKED_DAY_OVER] += 1
                raise over
            started = time.monotonic()
            try:
                response = await self.inner.complete(req)
            except ClaudeRateLimited as exc:
                self._log(req, "rate_limited", started)
                if self.waiter is not None and await self.waiter.wait(exc.reset_at):
                    continue
                self.unasked[UNASKED_LIMIT] += 1
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
        if (refused := self._refused(req)) is not None:
            yield StreamEvent(type="error", error=str(refused))
            return
        while True:
            if self.budget is not None and self.budget.reached:
                self.unasked[UNASKED_BUDGET] += 1
                yield StreamEvent(type="error", error=self.budget.refuse())
                return
            if (over := self._day_over()) is not None:
                self.unasked[UNASKED_DAY_OVER] += 1
                yield StreamEvent(type="error", error=str(over))
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
            self.unasked[UNASKED_LIMIT] += 1
            yield limited
            return


async def claude_version(binary: str | None = None) -> str | None:
    """``claude --version`` (zero tokens; no model is asked)."""
    return await claude_cli.version(binary)


@dataclass
class LiveSetup:
    """What a live run's stacks share: the budget, the waiting, the ``claude`` asked, its version, the ledgers, the
    provenance each new cassette is stamped with, the recording's day (``None``: not checked), the letters whose
    unit is already complete (a final split's: no call for them reaches the model), and the calls its stacks returned
    without an answer for a reason of the run, by reason (:attr:`LiveCalls.unasked`)."""

    repeat: int = 1
    budget: Budget | None = None
    waiter: LimitWaiter | None = None
    day: date | None = None
    closed: frozenset[str] = frozenset()
    cli: Any = None
    cli_version: str | None = None
    ledgers: list[Ledger] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    unasked: Counter[str] = field(default_factory=Counter)

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
    """The code paths (under ``src/`` and ``evals/``, not results, recordings or the deviations file) that differ
    from the commit, or ``None`` without git."""
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
        if path and not path.startswith(("evals/results/", "evals/recorded/")) and not _deviations_file(path):
            paths.append(path)
    return sorted(paths)


def shown(path: Path) -> str:
    """``path`` as a command typed from the repository's root would name it (the absolute path elsewhere)."""
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _deviations_file(path: str) -> bool:
    """The pre-registration's deviations file: recorded at the time, while a read may still be under way, and committed
    with the next checkpoint; it is no code a recording depends on."""
    return re.fullmatch(r"evals/preregistration/deviations-[^/]+\.json", path) is not None


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
    manifest: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Replay every recorded split (or ``splits``; or the letters ``ids``) with every condition and return the lock
    entry of each request made. Fails when a prediction errs (a missing recording, say). A final split's letters each
    take their unit's day from the day index beside the recordings, as every replay does (``evals/run.py``)."""
    from evals import run as eval_run
    from evals import splits as registry
    from evals.conditions import ordnung_prompt_hashes
    from evals.records import load_manifest

    manifest_path = manifest or eval_run.MANIFEST_PATH
    manifest_entries = load_manifest(manifest_path)
    allowed = {entry.id for entry in manifest_entries}
    wanted = set(ids or ())
    names = list(splits or registry.recorded())
    if wanted:
        names = [name for name in names if any(e.split == name and e.id in wanted for e in manifest_entries)]
    stale = eval_run.stale_prompts(recorded_dir / eval_run.safe_name(model), ordnung_prompt_hashes())
    if stale:
        raise HarnessError(f"the prompts changed since the recordings were made: {', '.join(stale)}")
    entries: dict[str, dict[str, Any]] = {}
    for name in names:
        selected = (
            sorted(e.id for e in manifest_entries if e.split == name and e.id in wanted) if wanted else None
        )
        config = eval_run.RunConfig(
            split=name,
            models=[model],
            ids=selected,
            manifest_path=manifest_path,
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
# Retaking a unit
# --------------------------------------------------------------------------------------------------


class NothingToRetake(HarnessError):
    """The unit asked for has no recording in the folder (a wrong id or repeat, or retaken already)."""


#: How each recorded call of a retaken unit went, from its ledger line: an answer, a model failure (scored, never
#: retaken alone), a timeout, or an infrastructure error (a usage limit, sign-in, a CLI that did not start …).
RETAKE_OUTCOMES = {"ok": "ok", "bad_output": "failed", "timeout": "timeout"}


def _cassette_cost(path: Path) -> float:
    try:
        usage = (json.loads(path.read_text(encoding="utf-8")).get("response") or {}).get("usage") or {}
        return float(usage.get("cost_usd") or 0.0)
    except (OSError, ValueError, AttributeError, TypeError):
        return 0.0


#: The deviations whose registered consequence records a read again (the pre-registration's table): the never-waivable
#: kinds, and the runner-defect rule's ``code_hash_changed``.
RECORD_AGAIN_KINDS = ("fingerprint", "code_digest", "prompt_hash", "model", "code_hash_changed")
DEVIATIONS_FILE = ROOT / "evals" / "preregistration" / "deviations-0.4.0.json"


def retake(
    recorded_dir: Path,
    *,
    to: Path,
    repeat: int,
    model: str = DEFAULT_MODEL,
    split: str | None = None,
    ids: Sequence[str] = (),
    whole_run: bool = False,
    complete_too: bool = False,
) -> list[str]:
    """Move an incomplete unit's recordings out of ``recorded_dir`` into ``to`` and remove their request-lock entries,
    so the unit is recorded again whole on its new day (a unit's calls are all told one today). A unit is the letters
    ``ids`` of ``split`` at run ``repeat``, or (``whole_run``) every recording of that run in the folder: an Ask run or
    a stress invocation is one unit, never in the benchmark's folder (where the final splits' day index lives). A
    complete unit (in the day index) is never retaken, unless ``complete_too`` (:func:`retake_invalid`: a read a
    deviation made invalid). The retaken units leave the day index.

    Returns one line per recording moved (path, sha256, outcome, cost) and per call of the unit that left no recording
    (a timeout, an infrastructure error): the evidence of the retake's deviation. Nothing is moved when any target
    exists already."""
    from evals.run import safe_name

    if whole_run == bool(ids):
        raise HarnessError(
            "retake takes the letters of a unit (--split S --ids …) or --whole-run, one of the two"
        )
    if ids and split is None:
        raise HarnessError("--ids names letters of one split: give --split too")
    root = recorded_dir / safe_name(model)
    index = DayIndex(root / DAY_INDEX_FILE)
    if whole_run:
        if split is not None:
            raise HarnessError(
                "--whole-run retakes an Ask run or a stress invocation, which have no split: not with --split (a "
                "benchmark's units are retaken with --split S --ids …)"
            )
        if recorded_dir.resolve() == RECORDED_DIR.resolve() or index.data:
            raise HarnessError(
                f"{root} holds the benchmark's recordings (and the final splits' day index): --whole-run would move "
                "every letter's recordings of that run. Name the Ask or stress run's own folder with --recorded-dir "
                "(evals/recorded/ask-heldout, evals/recorded/stress)"
            )
    if ids and split is not None and not complete_too:
        complete = index.units(split, repeat)
        done = sorted(set(ids) & set(complete))
        if done:
            days = ", ".join(sorted({str(complete[entry_id]["day"]) for entry_id in done}))
            raise HarnessError(
                f"{', '.join(done)}: complete at run {repeat} (recorded on {days}); a complete unit is never retaken"
            )
    lock = RequestLock(root / LOCK_FILE)
    selected = lock_entries_of(lock, repeat=repeat, docs=None if whole_run else ids)
    moves = [(key, path) for key in sorted(selected) for path in recordings_of(root, key)]
    what = f"run {repeat} of {recorded_dir}" if whole_run else f"{', '.join(ids)} at run {repeat}"
    if not moves:
        raise NothingToRetake(f"no cassette of {what} in {root}: nothing to retake")
    target_root = to / root.name
    targets = [target_root / path.relative_to(root) for _, path in moves]
    there = [str(target) for target in targets if target.exists()]
    if there:
        raise HarnessError(f"{there[0]} exists already: nothing was moved (retake into a fresh folder)")
    wanted = None if whole_run else set(ids)
    rows = [
        row
        for row in _ledger_rows(root)
        if int(row.get("repeat") or 1) == repeat
        and (wanted is None or wanted.intersection(row.get("docs") or []))
    ]
    answered = ("ok", "bad_output")
    lines: list[str] = []
    for key, path in moves:
        if path.name.endswith(".failure.json"):
            outcome = "failed"
        elif path.name.endswith(".bad"):
            outcome = "infra"
        else:
            outcome = "ok"
        made = [
            row
            for row in rows
            if f"{row.get('purpose')}/{row.get('key')}" == key and row.get("outcome") in answered
        ]
        cost = float(made[-1].get("cost_usd") or 0.0) if made else _cassette_cost(path)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{path.relative_to(recorded_dir).as_posix()} {sha} {outcome} ${cost:.4f}")
    for row in rows:
        if row.get("outcome") in answered:
            continue
        outcome = RETAKE_OUTCOMES.get(str(row.get("outcome")), "infra")
        lines.append(
            f"- {row.get('purpose')}/{row.get('key')} {outcome} ${float(row.get('cost_usd') or 0.0):.4f} "
            f"(no recording; called at {row.get('at')})"
        )
    for (_, path), target in zip(moves, targets, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
    for key in selected:
        del lock.entries[key]
    lock.save()
    if ids and split is not None:
        index.remove(split, repeat, ids)
    entries = "entry" if len(selected) == 1 else "entries"
    lines.append(
        f"moved {len(moves)} recording(s) of {what} to {target_root} and removed {len(selected)} request-lock "
        f"{entries}: record the unit again whole"
    )
    return lines


def retake_invalid(
    recorded_dir: Path,
    *,
    to: Path,
    deviation: str,
    deviations_file: Path = DEVIATIONS_FILE,
    model: str = DEFAULT_MODEL,
) -> list[str]:
    """Move aside every unit of a read that a deviation recorded at the time made invalid, complete ones too, so the
    read is recorded again inside the window: the registered consequence of a never-waivable deviation (fingerprint,
    code digest, prompt hash, served model) and of the runner-defect rule (``code_hash_changed``). The deviation must
    be in ``deviations_file``, well formed, of one of those kinds, and name the read (``applies_to`` split and repeat;
    its ``entries``, when it lists some, are the units). The read's results file is set aside by hand."""
    from evals.analysis import AnalysisError, load_deviations
    from evals.run import safe_name

    try:
        found = {entry.id: entry for entry in load_deviations(deviations_file)}
    except AnalysisError as exc:
        raise HarnessError(f"{deviations_file}: {exc}") from exc
    named = found.get(deviation)
    if named is None:
        raise HarnessError(f"{deviations_file.name} has no deviation {deviation}")
    if named.kind not in RECORD_AGAIN_KINDS:
        raise HarnessError(
            f"{deviation} is a {named.kind} deviation: only {', '.join(RECORD_AGAIN_KINDS)} make a read recorded "
            "again"
        )
    if named.split is None or named.repeat is None:
        raise HarnessError(f"{deviation} names no read (applies_to: split and repeat)")
    root = recorded_dir / safe_name(model)
    units = DayIndex(root / DAY_INDEX_FILE).attempted(named.split, named.repeat)
    lock = RequestLock(root / LOCK_FILE)
    recorded = {
        doc
        for entry in lock_entries_of(lock, repeat=named.repeat).values()
        for doc in entry.get("docs") or []
    }
    ids = sorted(named.entries) or sorted(
        units.keys() | {doc for doc in recorded if doc.startswith(f"{named.split}-")}
    )
    if not ids:
        raise NothingToRetake(
            f"{named.split} read {named.repeat} has nothing recorded in {root}: nothing to retake"
        )
    lines = retake(
        recorded_dir,
        to=to,
        repeat=named.repeat,
        model=model,
        split=named.split,
        ids=ids,
        complete_too=True,
    )
    lines.append(
        f"{named.split} read {named.repeat} is invalid ({deviation}, {named.kind}): its {len(ids)} unit(s) left the "
        "day index; set its results file aside, then record the read again whole inside the window"
    )
    return lines


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


#: Which requests' prompts hold the answers of which earlier requests of the same letter, by purpose: Ordnung reads a
#: picture letter from the transcript of its pages (``ordnung.ingest.pipeline``: ``transcribe_pages`` stores each
#: page's transcript as its text, and ``extraction_request`` puts the pages' text in the prompt), under a key that
#: names only where each page's text came from (``extraction_cache_key``). A repeat's reading of a photo therefore
#: repeats run 1's reading under its key, while its prompt holds this run's transcript. That is the only link across
#: purposes. A repair's prompt holds this run's validation problems, under the key of run 1's repair of the letter
#: (``ordnung.ingest.extract.repair_request``, ``evals.conditions.baseline_repair_request``): it is judged when run 1
#: made it too (no dev letter has one).
BUILT_ON: dict[str, tuple[str, ...]] = {"extract": ("transcribe",)}

#: Purposes of which a repeat must ask each of run 1's requests again, under its key, for every letter the repeat
#: read with Ordnung (made a request of one of these purposes, or of one in :data:`BUILT_ON`, for it): a
#: transcription is one call per page, with no follow-up, keyed by the sha256 of its page image
#: (``ordnung.ingest.transcribe.transcription_request``). Sent with other bytes (the page rendered by another
#: Pillow build, say), it is under another key, where the smoke would count it as a call run 1 never made.
ASKED_AGAIN: tuple[str, ...] = ("transcribe",)


def smoke_checks(scratch_root: Path, committed_root: Path, *, cap: float) -> dict[str, Any]:
    """Compare a repeat recorded into ``scratch_root`` with run 1's recordings in ``committed_root``.

    A repeat's first request of each letter and condition (a transcription, a text letter's reading, every
    baseline, every Ask turn) is run 1's request under a key of its own: it must be byte for byte the same request,
    and so must every other request the repeat makes under the key of one of run 1's
    (``requests_identical_to_run_1``; false when nothing was judged). Each of run 1's transcriptions of the letters
    the repeat read with Ordnung must be asked again (:data:`ASKED_AGAIN`; ``run_1_transcriptions_not_asked_again``,
    and ``requests_identical_to_run_1`` is false when one was not). One kind of request is counted, not judged
    (``built_on_answers_that_differ_from_run_1``): one whose prompt holds earlier answers of this run
    (:data:`BUILT_ON`: a photo's reading holds its pages' transcripts), when it differs from run 1's request in its
    prompt alone, the requests of its letter it is built on are run 1's (each of them asked again, byte for byte,
    and no other), and one of them got an answer that differs from run 1's. The model is not deterministic, so its
    prompt cannot be run 1's. A follow-up (a repair, a re-ask) depends on the answers: one run 1 never made is
    counted (``follow_ups_run_1_did_not_make``), not judged; one run 1 made too is judged."""
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

    def identical(entry: Mapping[str, Any]) -> bool:
        return committed[str(entry["of"])].get("content") == entry.get("content")

    def answered_otherwise(key: str, entry: Mapping[str, Any]) -> bool:
        mine, first = _recording(scratch_root, key), _recording(committed_root, str(entry["of"]))
        return mine.is_file() and first.is_file() and _answer(mine) != _answer(first)

    def of_letter(
        entries: Mapping[str, Mapping[str, Any]], purposes: Collection[str], letter: set[str]
    ) -> dict[str, Mapping[str, Any]]:
        return {
            key: entry
            for key, entry in entries.items()
            if key.partition("/")[0] in purposes and set(entry.get("docs") or []) == letter
        }

    def built_on_another_answer(key: str, entry: Mapping[str, Any]) -> bool:
        first, mine = entry_fields(committed[str(entry["of"])]), entry_fields(entry)
        if {name for name in FIELDS if mine.get(name) != first.get(name)} != {"prompt"}:
            return False
        letter = set(entry.get("docs") or [])
        upstream = BUILT_ON.get(key.partition("/")[0], ())
        built_on, run_1s = of_letter(lock, upstream, letter), of_letter(committed, upstream, letter)
        return (
            bool(letter)
            and {str(earlier.get("of")) for earlier in built_on.values()} == set(run_1s)
            and all(identical(earlier) for earlier in built_on.values())
            and any(answered_otherwise(other, earlier) for other, earlier in built_on.items())
        )

    built_on = {
        key for key, entry in repeated.items() if not identical(entry) and built_on_another_answer(key, entry)
    }
    judged = [entry for key, entry in repeated.items() if key not in built_on]
    read = {
        doc
        for key, entry in lock.items()
        if key.partition("/")[0] in {*ASKED_AGAIN, *BUILT_ON}
        for doc in entry.get("docs") or []
    }
    not_asked_again = {
        key
        for key, entry in committed.items()
        if key.partition("/")[0] in ASKED_AGAIN and set(entry.get("docs") or []) & read
    } - {str(entry["of"]) for entry in repeated.values()}
    return {
        "calls": len(ledger),
        "cassettes": len(cassettes),
        "locked": len(lock),
        "keys_differ_from_run_1": bool(lock) and not set(lock) & set(committed),
        "repeated": len(repeated),
        "follow_ups_run_1_did_not_make": len(lock) - len(repeated),
        "run_1_transcriptions_not_asked_again": len(not_asked_again),
        "requests_identical_to_run_1": bool(judged)
        and not not_asked_again
        and all(identical(entry) for entry in judged),
        "built_on_answers_that_differ_from_run_1": len(built_on),
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
    # the smoke repeats run 1 of dev letters on their own today, into a scratch folder that is thrown away
    base += ["--recorder-lock", str(recorder_lock), "--allow-another-today"]
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
                "--allow-another-today",
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
        command.add_argument("--manifest", type=Path, default=None, help=argparse.SUPPRESS)

    retake_cmd = commands.add_parser(
        "retake",
        help="move an incomplete unit's recordings aside (and their lock entries) so it is recorded again whole",
    )
    retake_cmd.add_argument("--to", type=Path, required=True, help="where the recordings go (a fresh folder)")
    retake_cmd.add_argument("--repeat", type=int, default=1, metavar="N", help="the run (default 1)")
    retake_cmd.add_argument("--split", help="the letters' split (with --ids)")
    retake_cmd.add_argument("--ids", nargs="+", default=[], help="the unit's letters")
    retake_cmd.add_argument(
        "--whole-run",
        action="store_true",
        help="every recording of the run in the folder (an Ask run, a stress run; give its --recorded-dir)",
    )
    retake_cmd.add_argument(
        "--invalid",
        metavar="ID",
        help="every unit of the read this deviation made invalid, complete ones too (a never-waivable deviation, or "
        "the runner-defect rule's code_hash_changed)",
    )
    retake_cmd.add_argument(
        "--deviations", type=Path, default=DEVIATIONS_FILE, help="the deviations file (with --invalid)"
    )
    retake_cmd.add_argument(
        "--recorded-dir", type=Path, default=None, help="recordings root (default: the benchmark's)"
    )
    retake_cmd.add_argument("--model", default=DEFAULT_MODEL)

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
        entries = capture_requests(
            root_dir, model=args.model, splits=args.splits, ids=args.ids, manifest=args.manifest
        )
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
        if args.command == "retake":
            if args.whole_run and args.recorded_dir is None:
                raise HarnessError(
                    "--whole-run needs the Ask or stress run's own folder: --recorded-dir evals/recorded/ask-heldout "
                    "or evals/recorded/stress"
                )
            if args.invalid and (args.whole_run or args.ids or args.split):
                raise HarnessError("--invalid names the read itself: not with --whole-run, --split or --ids")
            try:
                if args.invalid:
                    lines = retake_invalid(
                        args.recorded_dir or RECORDED_DIR,
                        to=args.to,
                        deviation=args.invalid,
                        deviations_file=args.deviations,
                        model=args.model,
                    )
                else:
                    lines = retake(
                        args.recorded_dir or RECORDED_DIR,
                        to=args.to,
                        repeat=args.repeat,
                        model=args.model,
                        split=args.split,
                        ids=args.ids,
                        whole_run=args.whole_run,
                    )
            except NothingToRetake as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            for line in lines:
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
