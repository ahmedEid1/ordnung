"""The request lock (``requests.lock.json`` beside the recordings, ``evals/harness.py``).

A replay key holds what identifies a request's *input* (the letter's hash, today, the prompt versions), not every
byte the model reads: a change to how the page text is laid out, say, leaves every key as it was, and a replay would
serve the old answers to a request that is no longer sent. The lock maps each recording's key to a hash of
everything the ``claude`` CLI gets (system, prompt, schema, model, tools, MCP server, allowed tools, budget and the
attachments' bytes), so a replay of a request that changed under the same key fails and names what changed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import conditions, harness  # noqa: E402
from evals import run as eval_run  # noqa: E402

from ordnung.assistant.mcp_server import server_config  # noqa: E402
from ordnung.assistant.rules_tools import rules_server_config  # noqa: E402
from ordnung.llm.base import Attachment, LLMRequest  # noqa: E402
from ordnung.llm.fake import FakeBackend  # noqa: E402
from test_evals_run import IDS, Responder, make_config  # noqa: E402

TEXT_LETTER = "dev-tax_assessment-A1"


def _request(tmp_path: Path, **overrides: Any) -> LLMRequest:
    page = tmp_path / "page.jpg"
    if not page.exists():
        page.write_bytes(b"\xff\xd8 a page")
    values: dict[str, Any] = {
        "purpose": "eval_baseline",
        "prompt": "the prompt",
        "system": "the system prompt",
        "schema": {"type": "object"},
        "attachments": [Attachment(path=page, media_type="image/jpeg")],
        "doc_ids": [TEXT_LETTER],
        "cache_key": "doc|today",
        "prompt_version": "llm_only.s3",
    }
    values.update(overrides)
    return LLMRequest(**values)


def _root(tmp_path: Path) -> Path:
    return tmp_path / "recorded" / eval_run.DEFAULT_MODEL


def _lock(tmp_path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_root(tmp_path) / harness.LOCK_FILE).read_text(encoding="utf-8"))
    return data


def _with_a_page_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every text letter's pages are laid out with one more line: the keys stay, the requests change."""
    original = conditions.page_delimited

    def delimited(pages: Any) -> str:
        return "Pages follow.\n" + original(pages)

    monkeypatch.setattr(conditions, "page_delimited", delimited)
    monkeypatch.setattr("ordnung.ingest.extract.page_delimited", delimited)


# --------------------------------------------------------------------------------------------------
# What the hash covers
# --------------------------------------------------------------------------------------------------


def test_the_hash_covers_what_the_cli_is_sent_and_nothing_else(tmp_path: Path) -> None:
    base = _request(tmp_path)
    digest = harness.request_sha256(base)
    fields = harness.request_fields(base)
    assert set(fields) == {
        "model",
        "system",
        "prompt",
        "schema",
        "tools",
        "mcp",
        "allowed_tools",
        "budget",
        "attachments",
    }
    never_sent = [
        {"cache_key": "another key"},
        {"prompt_version": "llm_only.s4"},
        {"timeout_s": 5.0},
        {"doc_ids": ["another-letter"]},
        {"prompt_name": "named"},
    ]
    for change in never_sent:
        assert harness.request_sha256(base.model_copy(update=change)) == digest, change
    sent = {
        "prompt": {"prompt": "another prompt"},
        "system": {"system": "another system prompt"},
        "schema": {"schema_": {"type": "array"}},
        "model": {"model": "another-model"},
        "tools": {"tools": ["Read"]},
        "allowed_tools": {"allowed_tools": ["mcp__x__*"]},
        "budget": {"max_budget_usd": 2.0},
        "mcp": {"mcp_config": {"mcpServers": {"x": {"command": "x"}}}},
    }
    for field, change in sent.items():
        changed = base.model_copy(update=change)
        assert harness.request_sha256(changed) != digest, field
        after = harness.request_fields(changed)
        assert [name for name in fields if fields[name] != after[name]] == [field]
    (tmp_path / "page.jpg").write_bytes(b"\xff\xd8 another page")
    assert harness.request_sha256(base) != digest
    assert harness.request_fields(base)["attachments"] != fields["attachments"]


def test_the_mcp_server_s_interpreter_and_data_folder_are_not_part_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = _request(tmp_path, mcp_config=rules_server_config(today="2026-10-01"))
    monkeypatch.setattr(sys, "executable", "/elsewhere/bin/python3")
    there = _request(tmp_path, mcp_config=rules_server_config(today="2026-10-01"))
    assert here.mcp_config != there.mcp_config
    assert harness.request_sha256(here) == harness.request_sha256(there)
    other_day = _request(tmp_path, mcp_config=rules_server_config(today="2026-10-02"))
    assert harness.request_sha256(other_day) != harness.request_sha256(there)

    one = _request(tmp_path, mcp_config=server_config(tmp_path / "one", rules_tools=False))
    two = _request(tmp_path, mcp_config=server_config(tmp_path / "two", rules_tools=False))
    assert harness.request_sha256(one) == harness.request_sha256(two)
    masked = _request(
        tmp_path, mcp_config=server_config(tmp_path / "two", rules_tools=False, masked_numbers=True)
    )
    assert harness.request_sha256(masked) != harness.request_sha256(two)


# --------------------------------------------------------------------------------------------------
# Recording and replaying with a lock
# --------------------------------------------------------------------------------------------------


async def test_a_live_recording_locks_every_request_it_records(tmp_path: Path) -> None:
    fake = FakeBackend(Responder())
    assert (
        await eval_run.run_benchmark(make_config(tmp_path, live=True, write_docs=False, live_backend=fake))
    ).ok
    root = _root(tmp_path)
    cassettes = {f"{p.parent.name}/{p.stem}" for p in root.rglob("*.json") if p.parent != root}
    lock = _lock(tmp_path)
    assert set(lock) == cassettes and len(lock) == len(fake.calls)
    for entry in lock.values():
        assert entry["docs"] and entry["docs"][0] in IDS
        assert len(entry["content"]) == 32 and list(harness.entry_fields(entry)) == list(harness.FIELDS)
        assert "repeat" not in entry and "of" not in entry
    replay = await eval_run.run_benchmark(
        make_config(tmp_path, write_docs=False, results_dir=tmp_path / "replay")
    )
    assert replay.ok


async def test_a_request_that_changed_under_its_key_is_a_stale_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeBackend(Responder())
    live = make_config(tmp_path, ids=[TEXT_LETTER], conditions=["llm_only"], live=True, write_docs=False)
    live.live_backend = fake
    assert (await eval_run.run_benchmark(live)).ok
    _with_a_page_header(monkeypatch)

    args = ["--split", "dev", "--ids", TEXT_LETTER, "--conditions", "llm_only", "--quiet", "--no-docs"]
    args += ["--recorded-dir", str(tmp_path / "recorded"), "--results-dir", str(tmp_path / "replay")]
    assert await _cli([*args, "--date", "2026-10-29", "--resamples", "20"]) == 1
    err = capsys.readouterr().err
    assert "stale recording" in err and "eval_baseline" in err and TEXT_LETTER in err
    assert "differs from requests.lock.json in: prompt" in err
    assert "1 request(s) differ from" in err and "python -m evals.harness diff-requests" in err
    assert "no recorded response" not in err  # not a missing recording: the gate never leaves it out
    assert not list((tmp_path / "replay").glob("*.json"))

    # a replay-first live run never records the changed request over the old answer
    calls = len(fake.calls)
    again = make_config(
        tmp_path, ids=[TEXT_LETTER], conditions=["llm_only"], live=True, resume=False, write_docs=False
    )
    again.live_backend = fake
    outcome = await eval_run.run_benchmark(again)
    assert not outcome.ok or outcome.runs[0].errors
    assert len(fake.calls) == calls

    # --refresh records it anew, on purpose, and locks the new request
    fresh = make_config(
        tmp_path,
        ids=[TEXT_LETTER],
        conditions=["llm_only"],
        live=True,
        refresh=True,
        resume=False,
        write_docs=False,
    )
    fresh.live_backend = fake
    assert (await eval_run.run_benchmark(fresh)).ok
    assert len(fake.calls) == calls + 1
    assert await _cli([*args, "--date", "2026-10-30", "--resamples", "20"]) == 0


async def test_a_recording_the_lock_does_not_know_is_refused(tmp_path: Path) -> None:
    ids = [TEXT_LETTER]
    live = make_config(tmp_path, ids=ids, conditions=["llm_only"], live=True, write_docs=False)
    live.live_backend = FakeBackend(Responder())
    assert (await eval_run.run_benchmark(live)).ok
    lock_path = _root(tmp_path) / harness.LOCK_FILE
    (key,) = _lock(tmp_path)
    lock_path.write_text("{}\n", encoding="utf-8")
    replay = make_config(
        tmp_path, ids=ids, conditions=["llm_only"], write_docs=False, results_dir=tmp_path / "r"
    )
    outcome = await eval_run.run_benchmark(replay)
    (error,) = outcome.runs[0].errors
    assert "not in requests.lock.json" in (error.error or "") and key in (error.error or "")

    # without a lock file (a scratch recording made before the lock existed) nothing is checked
    lock_path.unlink()
    assert (await eval_run.run_benchmark(replay)).ok


def test_diff_names_what_changed() -> None:
    def entry(**fields: str) -> dict[str, Any]:
        base = dict.fromkeys(("model", "system", "prompt", "schema", "attachments"), "0" * 8)
        base.update(fields)
        return {"purpose": "extract", "docs": ["a"], "content": "c" * 32, "fields": base}

    old = {"extract/aaa": entry(), "extract/bbb": entry(), "eval_baseline/ccc": entry()}
    new = {
        "extract/aaa": {**entry(prompt="1" * 8, system="2" * 8), "content": "d" * 32},
        "extract/ddd": entry(),
        "eval_baseline/ccc": entry(),
    }
    diff = harness.diff_locks(old, new)
    assert diff.changed == {"extract/aaa": ["prompt", "system"]}
    assert diff.missing == ["extract/bbb"] and diff.new == ["extract/ddd"]
    assert not diff.clean
    text = "\n".join(diff.lines())
    assert "1 request(s) changed under the same key" in text and "extract: prompt 1, system 1" in text
    assert harness.diff_locks(old, old).clean


async def test_diff_requests_against_a_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "recorded"
    live = make_config(tmp_path, ids=[TEXT_LETTER], live=True, write_docs=False)
    live.live_backend = FakeBackend(Responder())
    assert (await eval_run.run_benchmark(live)).ok
    committed = (_root(tmp_path) / harness.LOCK_FILE).read_text(encoding="utf-8")
    asked: list[tuple[str, str]] = []

    def lock_at(ref: str, path: Path) -> str:
        asked.append((ref, str(path)))
        return committed

    monkeypatch.setattr(harness, "_lock_at", lock_at)
    args = ["diff-requests", "some-ref", "--recorded-dir", str(root), "--split", "dev", "--ids", TEXT_LETTER]
    assert await _main(args) == 0
    assert asked and asked[0][0] == "some-ref"
    assert "no request changed" in capsys.readouterr().out
    _with_a_page_header(monkeypatch)
    assert await _main(args) == 1
    out = capsys.readouterr().out
    assert (
        "changed under the same key" in out
        and "eval_baseline: prompt 3" in out
        and "extract: prompt 1" in out
    )


async def _main(args: list[str]) -> int:
    """``python -m evals.harness`` from an async test (it runs its own event loop)."""
    return await asyncio.to_thread(harness.main, args)


async def _cli(args: list[str]) -> int:
    """``python -m evals.run`` from an async test (it runs its own event loop)."""
    return await asyncio.to_thread(eval_run.run_cli, args)


# --------------------------------------------------------------------------------------------------
# The committed locks (every split, and Ask)
# --------------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_every_replayed_request_matches_the_committed_lock(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main(["lock-requests", "--check"]) == 0, capsys.readouterr().out


@pytest.mark.slow
def test_every_ask_request_matches_its_committed_lock(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main(["lock-requests", "--ask", "--check"]) == 0, capsys.readouterr().out


@pytest.mark.slow
def test_a_page_layout_change_is_caught_on_every_letter_read_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_a_page_header(monkeypatch)
    current = harness.capture_requests(harness.RECORDED_DIR)
    diff = harness.diff_locks(harness.RequestLock(harness.lock_path(harness.RECORDED_DIR)).entries, current)
    assert not diff.missing and not diff.new
    by_purpose: dict[str, int] = {}
    for key in diff.changed:
        by_purpose[key.split("/")[0]] = by_purpose.get(key.split("/")[0], 0) + 1
    assert by_purpose == harness_expected_drift()
    assert all(fields == ["prompt"] for fields in diff.changed.values())


def harness_expected_drift() -> dict[str, int]:
    """Every extraction (photos too: the transcript is laid out as pages), and every baseline but the photos'."""
    return {"extract": 281, "eval_baseline": 696}
