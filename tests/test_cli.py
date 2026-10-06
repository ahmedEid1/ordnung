"""The ``ordnung`` command line: in-process commands with a fake model, the client of a running
server (a fake API), ``serve`` orchestration, ``demo``, ``doctor``, ``mcp``, ``openapi``, ``eval``,
friendly errors and the exclusive data-folder lock."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fixtures_llm import TAX_LETTER, TODAY, Router, fake_backend
from ordnung import cli, clock
from ordnung.app_context import AppContext, build_context
from ordnung.cli import app, reachable_server
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.demo import load_manifest
from ordnung.demo.loader import build_demo
from ordnung.llm.base import ClaudeNotInstalled, ClaudeTimeout
from ordnung.llm.fake import FakeBackend
from ordnung.locking import DataDirLock, DataDirLocked
from ordnung.models import Document, DocumentDetail, DocumentStatus, Item, Party
from ordnung.server import ServerInfo, read_server_info, write_server_info
from test_demo import model_answers, write_sample_life
from test_doctor import fake_claude

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process commands read letters with the canned fake model instead of ``claude``."""

    def context(data_dir: Path) -> AppContext:
        return build_context(data_dir, backend_obj=fake_backend())

    monkeypatch.setattr(cli, "open_context", context)


def invoke(*args: str) -> Any:
    return runner.invoke(app, list(args))


def plain(output: str) -> str:
    """Help text without terminal styling (Typer forces Rich styling on CI, e.g. GITHUB_ACTIONS)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", output)


# --------------------------------------------------------------------------------------------------
# basics
# --------------------------------------------------------------------------------------------------


def test_help_lists_every_command() -> None:
    result = invoke("--help")
    assert result.exit_code == 0
    for command in ("serve", "add", "brief", "ask", "demo", "doctor", "eval", "mcp", "openapi"):
        assert command in result.output


def test_version() -> None:
    result = invoke("--version")
    assert result.exit_code == 0 and result.output.startswith("ordnung ")


def test_importing_the_cli_stays_light() -> None:
    probe = (
        "import sys, ordnung.cli; "
        "heavy = [m for m in ('ordnung.db.store', 'ordnung.ingest.pipeline', 'ordnung.views', 'mcp', "
        "'uvicorn', 'httpx', 'fastapi') if m in sys.modules]; print(heavy)"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# --------------------------------------------------------------------------------------------------
# add / brief / ask in-process
# --------------------------------------------------------------------------------------------------


def test_add_reads_letters_in_process_and_prints_a_summary(
    tmp_path: Path, data_dir: Path, fake_model: None
) -> None:
    letter = tmp_path / "steuerbescheid.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    result = invoke("add", str(letter), "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Your letters" in result.output
    assert "Income tax assessment 2025" in result.output
    assert "Finanzamt Musterstadt" in result.output
    assert "2026" in result.output  # a next date
    store = Store.open(Paths(data_dir))
    try:
        documents = store.list_documents()
        assert [doc.status for doc in documents] in (["processed"], ["needs_review"])
        assert documents[0].source == "cli"
        assert store.list_items(doc_id=documents[0].id)
    finally:
        store.close()
    assert not (data_dir / "server.json").exists()


def test_add_private_keeps_the_letter_from_the_model(
    tmp_path: Path, data_dir: Path, fake_model: None
) -> None:
    letter = tmp_path / "private.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    result = invoke("--data-dir", str(data_dir), "add", str(letter), "--private")
    assert result.exit_code == 0, result.output
    assert "Private — not sent to Claude" in result.output
    store = Store.open(Paths(data_dir))
    try:
        logged = [entry.message for entry in store.list_activity(5, kinds=["document.private"])]
    finally:
        store.close()
    assert logged == ["Stored “private.pdf” privately · not sent to Claude"]


@pytest.mark.parametrize(
    ("status", "private", "expected"),
    [
        ("held", False, "Not read yet — not sent to Claude"),
        ("processed", True, "Private — not sent to Claude"),
    ],
)
def test_privacy_statuses_name_who_does_not_read_the_letter(
    status: DocumentStatus, private: bool, expected: str
) -> None:
    document = Document(
        id="doc_1",
        sha256="0" * 64,
        filename="bescheid.pdf",
        mime="application/pdf",
        created_at="2026-09-01T09:00:00+00:00",
        updated_at="2026-09-01T09:00:00+00:00",
        status=status,
        ai_private=private,
    )
    assert cli._status_text(document) == expected


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (ClaudeTimeout("Claude took too long to answer."), "Failed — Claude took too long to answer."),
        (ClaudeNotInstalled("The “claude” command was not found."), "Waiting for Claude"),
    ],
    ids=["failed", "waiting-for-claude"],
)
def test_add_exits_non_zero_when_a_letter_was_not_read(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, shown: str
) -> None:
    """A letter that failed — or waits for Claude to be installed — is stored, and the exit code says
    not everything was read (scripts can tell)."""
    router = Router()
    router.errors["extract"] = lambda: error
    monkeypatch.setattr(
        cli, "open_context", lambda folder: build_context(folder, backend_obj=fake_backend(router))
    )
    letter = tmp_path / "steuerbescheid.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    result = invoke("add", str(letter), "--data-dir", str(data_dir))
    assert result.exit_code == 1, result.output
    assert shown in result.output and "Not every letter was read" in result.output
    assert "Traceback" not in result.output
    if isinstance(error, ClaudeNotInstalled):
        assert "Claude Code isn't installed on this computer yet." in result.output


def test_add_rejects_unreadable_files_without_a_traceback(
    tmp_path: Path, data_dir: Path, fake_model: None
) -> None:
    junk = tmp_path / "archive.zip"
    junk.write_bytes(b"PK\x03\x04\x00\x00binary\x00\x01\x02\xff\xfe")
    result = invoke("add", str(junk), "--data-dir", str(data_dir))
    assert result.exit_code == 1
    assert "✗" in result.output and "Traceback" not in result.output


def test_add_waits_for_nobody_while_another_writer_holds_the_folder(
    tmp_path: Path, data_dir: Path, fake_model: None
) -> None:
    letter = tmp_path / "letter.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    with DataDirLock(data_dir, purpose="ordnung serve"):
        result = invoke("add", str(letter), "--data-dir", str(data_dir))
    assert result.exit_code == 1
    assert "Another Ordnung process" in result.output and "ordnung serve" in result.output


def test_add_refuses_the_demo_folder(tmp_path: Path, demo_life: Path, fake_model: None) -> None:
    letter = tmp_path / "letter.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    result = invoke("add", str(letter), "--data-dir", str(demo_life / "recorded"))
    assert result.exit_code == 1 and "demo folder" in result.output


def test_brief_without_the_model(tmp_path: Path, data_dir: Path, fake_model: None) -> None:
    letter = tmp_path / "letter.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    assert invoke("add", str(letter), "--data-dir", str(data_dir)).exit_code == 0
    result = invoke("brief", "--no-llm", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Your note for Fri 25 Sep 2026" in result.output
    assert "from your records" in result.output


def test_ask_in_process_streams_the_checked_answer(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = FakeBackend({"ask": "Nothing is due that I can see."})
    monkeypatch.setattr(cli, "open_context", lambda folder: build_context(folder, backend_obj=answers))
    result = invoke("ask", "What is due?", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Nothing is due that I can see." in result.output
    assert answers.calls[0].purpose == "ask"


def test_ask_never_prints_the_unchecked_draft(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review findings: the CLI printed the streamed (unchecked) answer as ordinary text, so an injected
    "extended to 31.12.2027" stood on the terminal like the answer — and (round 4) even dimmed as a
    draft the person read it before it was left out. The words are no longer streamed at all."""
    answers = FakeBackend({"ask": "Your deadline was extended to 31.12.2027. Keep the letter."})
    monkeypatch.setattr(cli, "open_context", lambda folder: build_context(folder, backend_obj=answers))
    result = invoke("ask", "What is due?", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "31.12.2027" not in result.output and "Keep the letter." in result.output
    assert "Writing the answer" in " ".join(result.output.split())
    printer = cli._AnswerPrinter()
    with cli.console.capture() as shown:
        printer.handle({"type": "text", "text": "Extended to 31.12.2027."})
    assert "31.12.2027" not in shown.get()
    with cli.err_console.capture() as captured:
        printer.handle({"type": "error", "error": "The answer stopped unexpectedly."})
    assert "The answer stopped unexpectedly." in captured.get() and printer.failed


def test_ask_prints_the_check_note_apart(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = FakeBackend({"ask": "Pay 999.00 € by 1 Jan 2031. Keep the letter."})
    monkeypatch.setattr(cli, "open_context", lambda folder: build_context(folder, backend_obj=answers))
    result = invoke("ask", "What is due?", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Keep the letter." in result.output
    assert "Checked by Ordnung: Left out 1 sentence" in " ".join(result.output.split())
    # a German note gets the German label (review round 4)
    printer = cli._AnswerPrinter()
    with cli.console.capture() as shown:
        printer.handle(
            {"type": "done", "text": "Die Frist ist …", "note": "1 Satz weggelassen: Er nennt ein Gesetz."}
        )
    assert "Von Ordnung geprüft: 1 Satz weggelassen" in shown.get()
    # final review: the label comes with the answer (the backend knows its language) — a German note
    # with few German words is no longer guessed English
    forged = "1 Zeile weggelassen, die wie dieser Hinweis aussah: Nur Ordnung schreibt ihn."
    with cli.console.capture() as shown:
        printer.handle(
            {"type": "done", "text": "Die Frist …", "note": forged, "note_label": "Von Ordnung geprüft:"}
        )
    assert f"Von Ordnung geprüft: {forged}" in " ".join(shown.get().split())


def test_ask_says_an_unchanged_answer_was_checked(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Final review: the CLI printed no check line for an answer the check did not change (ADR 0008 says
    it reads "Dates and amounts checked against your records" — final review 3: not "Checked against
    your records", which read as if every claim was checked); the demo's "no recording" answer was never
    checked."""
    answers = FakeBackend({"ask": "I couldn't find that. Keep the letter."})
    monkeypatch.setattr(cli, "open_context", lambda folder: build_context(folder, backend_obj=answers))
    result = invoke("ask", "What is due?", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert cli.CHECKED_LINE in result.output
    assert cli.CHECKED_LINE == "Dates and amounts checked against your records."
    printer = cli._AnswerPrinter()
    with cli.console.capture() as shown:
        printer.handle({"type": "done", "text": "The demo uses recorded answers …"})
    assert cli.CHECKED_LINE not in shown.get()
    with cli.console.capture() as german:
        printer.handle(
            {
                "type": "done",
                "text": "Frist: Mi. 21.10.2026",
                "message_id": "msg_1",
                "note_label": "Von Ordnung geprüft:",
            }
        )
    assert cli.CHECKED_LINE_DE in german.get()


# --------------------------------------------------------------------------------------------------
# talking to a running server
# --------------------------------------------------------------------------------------------------


def _document(**fields: Any) -> Document:
    stamp = "2026-09-25T10:00:00Z"
    base = {"id": "doc_aaaaaaaaaaaa", "sha256": "0" * 64, "filename": "letter.pdf", "mime": "application/pdf"}
    return Document.model_validate(base | {"created_at": stamp, "updated_at": stamp} | fields)


class FakeApi(BaseHTTPRequestHandler):
    """Just enough of Ordnung's API for the CLI client."""

    server: FakeServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: Any) -> None:
        self._reply(200, json.dumps(value).encode())

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.requests.append((self.command, self.path, dict(self.headers), body))

    def do_GET(self) -> None:
        self._record()
        if self.path == "/api/health":
            self._json({"data_dir": str(self.server.data_dir), "today": TODAY})
        elif self.path == "/api/jobs?active_only=true":
            stamp = "2026-09-25T10:00:00Z"
            reason = "Waiting for Claude: Claude Code isn't signed in. Ordnung reads this letter as soon as …"
            job = {"id": "job_1", "doc_id": "doc_aaaaaaaaaaaa", "waiting_reason": reason}
            self._json([job | {"created_at": stamp, "updated_at": stamp}] if self.server.waiting else [])
        elif self.path.startswith("/api/documents/") and self.server.waiting:
            self._json(DocumentDetail(document=_document(status="queued")).model_dump(mode="json"))
        elif self.path == "/api/brief":
            self._json({"date": TODAY, "text": "Two things this week.", "source": "template"})
        elif self.path.startswith("/api/documents/"):
            stamp = "2026-09-25T10:00:00Z"
            detail = DocumentDetail(
                document=_document(status="needs_review", title="Parking fine"),
                party=Party(
                    id="pty_aaaaaaaaaaaa", name="Stadt Musterstadt", created_at=stamp, updated_at=stamp
                ),
                items=[
                    Item(
                        id="itm_aaaaaaaaaaaa",
                        kind="payment",
                        title="Pay the fine",
                        due_date="2026-10-09",
                        created_at=stamp,
                        updated_at=stamp,
                    )
                ],
            )
            self._json(detail.model_dump(mode="json"))
        else:
            self._reply(404, b'{"detail": "not found"}')

    def do_POST(self) -> None:
        self._record()
        if self.path == "/api/ask":
            events = [
                {"type": "tool_use", "name": "search", "text": "Searched your letters for “fine”"},
                {"type": "tool_result", "name": "search", "text": "Found 1 letter"},
                {"type": "text", "text": "Pay the fine "},
                {"type": "text", "text": "by 9 Oct [doc:doc_zzzzzzzzzzzz]."},
                {
                    "type": "done",
                    "text": "Pay the fine by 9 Oct.",
                    "citations": [{"type": "document", "id": "doc_aaaaaaaaaaaa", "label": "Parking fine"}],
                },
            ]
            body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
            self._reply(200, body, "text/event-stream")
        elif self.path == "/api/brief":
            self._json({"date": TODAY, "text": "Written anew.", "source": "llm"})
        elif self.path == "/api/brief?llm=false":
            self._json({"date": TODAY, "text": "Two things this week.", "source": "template"})
        elif self.path == "/api/documents":
            self._json({"documents": [_document(status="queued").model_dump(mode="json")], "jobs": []})
        else:
            self._reply(404, b'{"detail": "not found"}')


class FakeServer(ThreadingHTTPServer):
    data_dir: Path
    requests: list[tuple[str, str, dict[str, str], bytes]]
    #: the letter added stays queued, its job waiting for Claude
    waiting: bool = False


@pytest.fixture
def api(data_dir: Path) -> Iterator[FakeServer]:
    """A fake Ordnung server for ``data_dir``, announced in its ``server.json``."""
    server = FakeServer(("127.0.0.1", 0), FakeApi)
    server.data_dir, server.requests = data_dir, []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    write_server_info(data_dir, ServerInfo(port=port, token="secret", pid=os.getpid()))
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def test_a_stale_server_json_is_ignored(data_dir: Path) -> None:
    dead = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True
    )
    write_server_info(data_dir, ServerInfo(port=9, pid=int(dead.stdout)))
    assert reachable_server(data_dir) is None
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    write_server_info(data_dir, ServerInfo(port=port, pid=os.getpid()))
    assert reachable_server(data_dir) is None  # alive, but nothing answers


def test_a_server_for_another_folder_is_not_used(api: FakeServer, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "server.json").write_text((api.data_dir / "server.json").read_text())
    assert reachable_server(other) is None
    assert reachable_server(api.data_dir) is not None


def test_ask_goes_through_the_running_server(api: FakeServer) -> None:
    result = invoke("ask", "When do I pay the fine?", "--data-dir", str(api.data_dir))
    assert result.exit_code == 0, result.output
    assert "↳ Searched your letters for “fine”" in result.output
    assert "Found 1 letter" in result.output
    assert "Pay the fine by 9 Oct." in result.output
    # an older server that still streams the words: the CLI shows only the checked answer
    assert "Pay the fine by 9 Oct [doc" not in result.output and "Pay the fine \n" not in result.output
    assert "Sources" in result.output and "Parking fine" in result.output
    method, path, headers, body = api.requests[-1]
    assert (method, path) == ("POST", "/api/ask")
    assert headers["Authorization"] == "Bearer secret" and headers["X-Ordnung-Client"] == "cli"
    assert json.loads(body) == {"question": "When do I pay the fine?"}


def test_brief_goes_through_the_running_server(api: FakeServer) -> None:
    result = invoke("brief", "--data-dir", str(api.data_dir))
    assert result.exit_code == 0 and "Written anew." in result.output
    assert "written by Claude" in result.output
    # --no-llm writes the note from the records, never shows the stored one Claude wrote (walkthrough of
    # phase 2: it printed "written by Claude, checked against your records")
    result = invoke("brief", "--no-llm", "--data-dir", str(api.data_dir))
    assert result.exit_code == 0 and "Two things this week." in result.output
    assert "written by Claude" not in result.output
    assert [(m, p) for m, p, _, _ in api.requests if p.startswith("/api/brief")] == [
        ("POST", "/api/brief"),
        ("POST", "/api/brief?llm=false"),
    ]


def test_add_goes_through_the_running_server(api: FakeServer, tmp_path: Path) -> None:
    photo = tmp_path / "fine.pdf"
    photo.write_bytes(TAX_LETTER.pdf())
    result = invoke("add", str(photo), "--combine", "--data-dir", str(api.data_dir))
    assert result.exit_code == 0, result.output
    assert "Parking fine" in result.output and "Stadt Musterstadt" in result.output
    assert "Fri 09 Oct 2026 · Pay the fine" in result.output and "Please check" in result.output
    upload = next(body for method, path, _, body in api.requests if path == "/api/documents")
    assert b'name="combine"' in upload and b"true" in upload and b'filename="fine.pdf"' in upload


def test_add_through_the_server_stops_waiting_for_a_letter_that_waits_for_claude(
    api: FakeServer, tmp_path: Path
) -> None:
    """The running app keeps the letter until Claude is ready; the command says so instead of hanging."""
    api.waiting = True
    letter = tmp_path / "letter.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    result = invoke("add", str(letter), "--data-dir", str(api.data_dir))
    assert result.exit_code == 1, result.output
    assert "Waiting for Claude" in result.output and "isn't signed in" in result.output


# --------------------------------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------------------------------


def test_serve_holds_the_folder_and_writes_server_json(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "_create_app", lambda context, token, demo: {"token": token, "demo": demo})

    def fake_run(self: uvicorn.Server) -> None:
        seen["info"] = read_server_info(data_dir)
        seen["app"], seen["loop"] = self.config.app, self.config.loop
        with pytest.raises(DataDirLocked):
            DataDirLock(data_dir).acquire()

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = invoke("serve", "--no-browser", "--port", str(port), "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    info = seen["info"]
    assert info.port == port and info.pid == os.getpid() and info.token
    assert info.login_url == f"http://127.0.0.1:{port}/?token={info.token}"
    assert info.login_url in result.output.replace("\n", "").replace("│", "").replace(" ", "")
    assert seen["app"] == {"token": info.token, "demo": False}
    assert seen["loop"] == "asyncio"  # not uvloop: it runs Python in the child it forks to start `claude`
    assert not (data_dir / "server.json").exists()
    DataDirLock(data_dir).acquire().release()


def test_sigterm_ends_the_server_through_its_cleanup() -> None:
    import signal

    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as stopped, cli._graceful_sigterm():
        signal.raise_signal(signal.SIGTERM)
    assert stopped.value.code == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) == before


def test_serve_on_a_busy_port_explains_what_to_do(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_create_app", lambda context, token, demo: object())
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        result = invoke("serve", "--no-browser", "--port", str(port), "--data-dir", str(data_dir))
    assert result.exit_code == 1
    assert f"Port {port} is already in use" in result.output and f"--port {port + 1}" in result.output


def test_serve_points_to_an_already_running_server(api: FakeServer) -> None:
    result = invoke("serve", "--no-browser", "--data-dir", str(api.data_dir))
    assert result.exit_code == 0 and "already running" in result.output


# --------------------------------------------------------------------------------------------------
# demo
# --------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_life(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The mini sample life recorded with the packaged suggested questions, plus its snapshot."""
    root = tmp_path_factory.mktemp("cli-life")
    samples = write_sample_life(root / "samples")
    ids = load_manifest(samples).document_ids(samples)
    build_demo(
        root / "recorded",
        backend="record",
        samples=samples,
        fixtures=root / "fixtures",
        live=model_answers(ids),
        snapshot=root / "snapshot",
        rebuild=True,
    )
    clock.set_today(None)
    return root


@pytest.fixture
def demo_env(demo_life: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ORDNUNG_SAMPLES", str(demo_life / "samples"))
    monkeypatch.setenv("ORDNUNG_FIXTURES", str(demo_life / "fixtures"))
    monkeypatch.setenv("ORDNUNG_DEMO_DB", str(demo_life / "snapshot"))
    monkeypatch.setenv("ORDNUNG_DEMO_HOME", str(demo_life / "home"))
    return demo_life


def test_demo_check_passes(demo_env: Path) -> None:
    result = invoke("demo", "--check")
    assert result.exit_code == 0, result.output
    assert "complete and reproducible" in result.output


def test_demo_check_fails_on_a_missing_recording(
    demo_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    fixtures = tmp_path / "fixtures"
    shutil.copytree(demo_env / "fixtures", fixtures)
    shutil.rmtree(fixtures / "brief")
    monkeypatch.setenv("ORDNUNG_FIXTURES", str(fixtures))
    result = invoke("demo", "--check")
    assert result.exit_code == 1
    assert "replay miss: brief" in result.output and "The demo check failed" in result.output


def test_demo_prepares_its_own_folder(demo_env: Path) -> None:
    result = invoke("demo", "--no-serve")
    assert result.exit_code == 0, result.output
    assert (demo_env / "home" / "ordnung.db").is_file()
    assert "The demo is ready" in result.output


def test_demo_ignores_ordnung_home(demo_env: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORDNUNG_HOME", str(data_dir))
    assert invoke("demo", "--no-serve").exit_code == 0
    assert not (data_dir / "ordnung.db").exists()


def test_demo_never_overwrites_real_data(demo_env: Path, data_dir: Path) -> None:
    Store.open(Paths(data_dir)).close()
    result = invoke("demo", "--no-serve", "--reset", "--data-dir", str(data_dir))
    assert result.exit_code == 1 and "refusing to overwrite" in result.output


def test_recording_needs_explicit_consent(demo_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORDNUNG_RECORD", raising=False)
    result = invoke("demo", "--live", "--rebuild", "--no-serve")
    assert result.exit_code == 1 and "ORDNUNG_RECORD=1" in result.output


def test_demo_serves_the_demo_folder_with_replay(demo_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    seen: dict[str, Any] = {}

    def create(context: AppContext, token: str | None, demo: bool) -> object:
        seen.update(backend=context.backend_name, demo=demo, today=clock.today().isoformat())
        return object()

    monkeypatch.setattr(cli, "_create_app", create)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: seen.update(loop=self.config.loop))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = invoke("demo", "--no-browser", "--port", str(port), "--reset")
    assert result.exit_code == 0, result.output
    assert seen == {"backend": "replay", "demo": True, "today": TODAY, "loop": "asyncio"}
    assert "Ordnung demo" in result.output


@pytest.mark.parametrize(
    "args", [("--reset",), ("--rebuild",), ("--reset", "--no-serve")], ids=["reset", "rebuild", "no-serve"]
)
def test_demo_reset_while_the_demo_runs_says_to_stop_it_first(
    demo_env: Path, api: FakeServer, args: tuple[str, ...]
) -> None:
    """Settings → Data and Ask send people to ``ordnung demo --reset`` while the demo runs: it used to
    say "already running", exit 0 and reset nothing."""
    result = invoke("demo", *args, "--no-browser", "--data-dir", str(api.data_dir))
    assert result.exit_code == 1, result.output
    port = api.server_address[1]
    option = args[0]
    assert " ".join(result.output.split()) == (
        f"✗ The demo is running at http://127.0.0.1:{port}. "
        f"Stop the demo (Ctrl+C where it runs), then run `ordnung demo {option}`."
    )
    assert not (api.data_dir / "ordnung.db").exists()


# --------------------------------------------------------------------------------------------------
# doctor / mcp / openapi / eval
# --------------------------------------------------------------------------------------------------


def test_doctor_with_a_fake_claude(tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    fake_claude(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin{os.pathsep}/usr/bin")
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = invoke("doctor", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Claude sign-in" in result.output and "Signed in (claude.ai)" in result.output
    assert "2.1.5" in result.output


def test_doctor_probes_on_the_model_every_call_runs_on(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--probe`` tries the model saved under Settings → Claude — the default before there is any data
    (and the folder is not created for it) — and the row names it."""
    from ordnung import doctor
    from ordnung.llm.claude_cli import ProbeResult

    bin_dir = tmp_path / "bin"
    fake_claude(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin{os.pathsep}/usr/bin")
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    probed: list[str | None] = []

    async def probe(
        binary: str | None = None, timeout_s: float = 60, *, model: str | None = None
    ) -> ProbeResult:
        probed.append(model)
        return ProbeResult(True, "OK", model or "haiku")

    monkeypatch.setattr(doctor.claude_cli, "probe", probe)
    result = invoke("doctor", "--probe", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert probed == ["claude-sonnet-5"] and "(on claude-sonnet-5)" in result.output
    assert not Paths(data_dir).db.exists()
    with Store.open(Paths(data_dir)) as store:
        store.save_settings(store.get_settings().model_copy(update={"model": "claude-opus-5-5"}))
    result = invoke("doctor", "--probe", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert probed == ["claude-sonnet-5", "claude-opus-5-5"] and "(on claude-opus-5-5)" in result.output
    # zero tokens without --probe
    assert invoke("doctor", "--data-dir", str(data_dir)).exit_code == 0 and len(probed) == 2


def test_doctor_without_claude_fails_with_a_fix(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    result = invoke("doctor", "--data-dir", str(data_dir))
    assert result.exit_code == 1
    assert "https://claude.com/claude-code" in result.output


def test_doctor_names_a_damaged_database_and_the_way_back(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``serve`` sends a damaged database to the doctor, which must say so (also with ``--probe``,
    which reads the chosen model from that database)."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with Store.open(Paths(data_dir)) as store:
        for n in range(300):
            store.set_meta(f"key-{n}", "x" * 200)
    db = Paths(data_dir).db
    db.write_bytes(db.read_bytes()[: db.stat().st_size // 3])
    for args in ((), ("--probe",)):
        result = invoke("doctor", *args, "--data-dir", str(data_dir))
        assert result.exit_code == 1, result.output
        assert "Database" in result.output and "ordnung restore FILE --force" in plain(result.output)


def test_a_database_from_a_newer_ordnung_is_explained(data_dir: Path) -> None:
    import sqlite3

    from ordnung.db.migrate import latest_version

    with Store.open(Paths(data_dir)):
        pass
    with sqlite3.connect(Paths(data_dir).db) as conn:
        conn.execute(f"PRAGMA user_version = {latest_version() + 1}")
    result = invoke("brief", "--no-llm", "--data-dir", str(data_dir))
    assert result.exit_code == 1
    out = plain(result.output)
    assert "A newer version of Ordnung wrote this database" in out and "Unexpected error" not in out
    assert "Update Ordnung, or restore a backup made with this version" in out


def test_mcp_help() -> None:
    result = invoke("mcp", "--help")
    assert result.exit_code == 0
    assert "--data-dir" in plain(result.output) and "--print-config" in plain(result.output)


def test_mcp_print_config(data_dir: Path) -> None:
    result = invoke("mcp", "--print-config", "--data-dir", str(data_dir))
    assert result.exit_code == 0
    server = json.loads(result.output)["mcpServers"]["ordnung"]
    assert server["args"] == ["-m", "ordnung", "mcp", "--data-dir", str(data_dir.resolve())]
    ledger_only = invoke("mcp", "--print-config", "--ledger-only", "--data-dir", str(data_dir))
    assert json.loads(ledger_only.output)["mcpServers"]["ordnung"]["args"][-1] == "--ledger-only"
    assert "--ledger-only" not in plain(invoke("mcp", "--help").output)  # Ask's switch, not for people


def test_mcp_without_a_database_says_so_on_stderr(tmp_path: Path) -> None:
    result = invoke("mcp", "--data-dir", str(tmp_path / "nothing"))
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "no Ordnung database" in result.stderr


def test_openapi_prints_the_schema() -> None:
    pytest.importorskip("ordnung.api.app")
    result = invoke("openapi")
    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert schema["openapi"].startswith("3.")
    assert "/api/health" in schema["paths"]


def test_eval_explains_when_the_runner_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_evals_module", lambda: None)
    result = invoke("eval")
    assert result.exit_code == 1 and "evals/run.py" in result.output


def test_eval_hands_every_argument_to_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []
    runner_module = type("Runner", (), {"run_cli": staticmethod(lambda argv: received.append(argv) or 3)})
    monkeypatch.setattr(cli, "_evals_module", lambda: runner_module)
    result = invoke("eval", "--live", "--split", "dev", "--models", "sonnet", "haiku")
    assert result.exit_code == 3
    assert received == [["--live", "--split", "dev", "--models", "sonnet", "haiku"]]
    assert invoke("eval", "--help").exit_code == 3
    assert received[-1] == ["--help"]


def test_eval_runs_the_real_runner_in_a_source_checkout() -> None:
    module = cli._evals_module()
    if module is None:
        pytest.skip("not a source checkout")
    result = invoke("eval", "--help")
    assert result.exit_code == 0
    assert "--split" in result.output


# --------------------------------------------------------------------------------------------------
# the lock
# --------------------------------------------------------------------------------------------------


def test_the_lock_keeps_a_second_writer_out(data_dir: Path) -> None:
    first = DataDirLock(data_dir, purpose="ordnung add")
    with first:
        assert first.locked
        with pytest.raises(DataDirLocked) as refused:
            DataDirLock(data_dir).acquire()
        assert refused.value.holder == f"pid {os.getpid()}: ordnung add"
        assert str(data_dir) in str(refused.value)
    assert not first.locked
    with DataDirLock(data_dir) as second:
        assert second.locked


def test_the_lock_waits_up_to_its_timeout(data_dir: Path) -> None:
    holder = DataDirLock(data_dir).acquire()
    releaser = threading.Timer(0.2, holder.release)
    releaser.start()
    started = time.monotonic()
    with DataDirLock(data_dir, timeout=5.0) as waiting:
        assert waiting.locked
    assert 0.15 <= time.monotonic() - started < 5.0
    with holder, pytest.raises(DataDirLocked):
        DataDirLock(data_dir, timeout=0.1).acquire()


def test_a_lock_held_by_another_process_blocks_until_it_exits(data_dir: Path) -> None:
    code = (
        "import sys, time; from ordnung.locking import DataDirLock; "
        "lock = DataDirLock(sys.argv[1], purpose='other').acquire(); print('held', flush=True); time.sleep(30)"
    )
    other = subprocess.Popen([sys.executable, "-c", code, str(data_dir)], stdout=subprocess.PIPE, text=True)
    try:
        assert other.stdout is not None and other.stdout.readline().strip() == "held"
        with pytest.raises(DataDirLocked, match="other"):
            DataDirLock(data_dir).acquire()
    finally:
        other.kill()
        other.wait()
    with DataDirLock(data_dir, timeout=2.0) as mine:  # the OS released it with the process
        assert mine.locked
