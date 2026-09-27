"""The trace API (``/api/documents/{id}/trace``, ``…/compare``, ``/api/traces``), the OpenTelemetry
export and ``ordnung trace``, and migration 0004 on an empty database, an older one with usage rows and
the prebuilt demo database."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fixtures_llm import APPOINTMENT_LETTER, TAX_LETTER
from ordnung import cli, clock
from ordnung.app_context import build_context
from ordnung.cli import app
from ordnung.config import Paths
from ordnung.db.migrate import MIGRATIONS_DIR, latest_version, migrate
from ordnung.db.store import Store
from ordnung.demo.loader import DEFAULT_SNAPSHOT
from ordnung.ingest.pipeline import add_file
from ordnung.llm.fake import FakeBackend
from ordnung.models import DocumentTrace
from ordnung.server import ServerInfo
from ordnung.trace.otel import SPAN_KIND_CLIENT, SPAN_KIND_INTERNAL, any_value, to_otlp
from ordnung.trace.view import document_trace
from test_api_support import TODAY, ApiRouter, api_for

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _read_tax_letter(data_dir: Path) -> str:
    ctx = build_context(data_dir, backend_obj=FakeBackend(ApiRouter()))
    try:
        document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
        await ctx.worker.run_until_idle()
        return document.id
    finally:
        ctx.close()


# --------------------------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------------------------


async def test_the_trace_of_a_letter_and_its_readings(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        upload = await api.client.post("/api/documents", files=[("files", ("b.pdf", TAX_LETTER.pdf()))])
        doc_id = upload.json()["documents"][0]["id"]
        assert await api.read_all() == 1
        response = await api.client.get(f"/api/documents/{doc_id}/trace")
        assert response.status_code == 200, response.text
        trace = response.json()
        assert trace["doc_id"] == doc_id and trace["run"]["reading"] == 1 and len(trace["runs"]) == 1
        assert trace["spans"][0]["kind"] == "run" and trace["spans"][0]["depth"] == 0
        model = next(span for span in trace["spans"] if span["kind"] == "model")
        assert model["call"]["prompt_name"] == "extract" and model["call"]["outcome"] == "ok"

        nothing = await api.client.get(f"/api/documents/{doc_id}/trace/compare")
        assert nothing.status_code == 404 and "read only once" in nothing.json()["detail"]

        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        assert await api.read_all() == 1
        latest = (await api.client.get(f"/api/documents/{doc_id}/trace")).json()
        assert [run["reading"] for run in latest["runs"]] == [2, 1]
        compared = await api.client.get(f"/api/documents/{doc_id}/trace/compare")
        assert compared.status_code == 200, compared.text
        body = compared.json()
        assert (body["base"]["reading"], body["head"]["reading"]) == (1, 2)
        assert body["changes"] == [], "the same answers decide the same things"

        older = latest["runs"][1]["trace_id"]
        first = (await api.client.get(f"/api/documents/{doc_id}/trace", params={"run": older})).json()
        assert first["run"]["reading"] == 1 and first["run"]["trace_id"] == older
        explicit = await api.client.get(
            f"/api/documents/{doc_id}/trace/compare",
            params={"base": latest["run"]["trace_id"], "head": older},
        )
        assert explicit.json()["base"]["reading"] == 2 and explicit.json()["head"]["reading"] == 1


async def test_missing_letters_readings_and_bad_ids(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        upload = await api.client.post("/api/documents", files=[("files", ("b.pdf", TAX_LETTER.pdf()))])
        doc_id = upload.json()["documents"][0]["id"]
        await api.read_all()
        missing = await api.client.get("/api/documents/doc_nothere/trace")
        assert missing.status_code == 404 and "doesn't exist" in missing.json()["detail"]
        gone = await api.client.get(f"/api/documents/{doc_id}/trace", params={"run": "trc_0123456789abcdef"})
        assert gone.status_code == 404 and "isn't kept" in gone.json()["detail"]
        for bad in ("../../etc", "trc_XYZ", "x" * 60):
            refused = await api.client.get(f"/api/documents/{doc_id}/trace", params={"run": bad})
            assert refused.status_code == 422, bad


async def test_a_letter_read_before_traces_were_kept_has_an_empty_trace(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        upload = await api.client.post("/api/documents", files=[("files", ("b.pdf", TAX_LETTER.pdf()))])
        doc_id = upload.json()["documents"][0]["id"]
        await api.read_all()
        api.ctx.store._conn().execute("DELETE FROM trace_spans")
        trace = (await api.client.get(f"/api/documents/{doc_id}/trace")).json()
        assert trace == {"doc_id": doc_id, "run": None, "runs": [], "spans": []}


async def test_the_export_holds_every_kept_reading_of_live_letters(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        upload = await api.client.post(
            "/api/documents",
            files=[("files", ("b.pdf", TAX_LETTER.pdf())), ("files", ("t.pdf", APPOINTMENT_LETTER.pdf()))],
            data={"combine": "false"},
        )
        tax, appointment = (document["id"] for document in upload.json()["documents"])
        await api.read_all()
        await api.client.delete(f"/api/documents/{appointment}")  # to the trash
        exported = (await api.client.get("/api/traces")).json()
        assert {span["doc_id"] for span in exported["spans"]} == {tax}
        span_ids = {span["id"] for span in exported["spans"]}
        assert exported["calls"] and all(call["span_id"] in span_ids for call in exported["calls"])


# --------------------------------------------------------------------------------------------------
# OpenTelemetry
# --------------------------------------------------------------------------------------------------


async def test_the_otel_export_follows_otlp_json_and_the_genai_conventions(data_dir: Path) -> None:
    doc_id = await _read_tax_letter(data_dir)
    with Store.open(Paths(data_dir)) as store:
        trace = document_trace(store, doc_id)
    exported = to_otlp(trace)
    assert exported == to_otlp(trace), "the same reading exports the same file"
    [resource] = exported["resourceSpans"]
    assert {"key": "service.name", "value": {"stringValue": "ordnung"}} in resource["resource"]["attributes"]
    [scope] = resource["scopeSpans"]
    spans = scope["spans"]
    assert len(spans) == len(trace.spans)
    ids = {span["spanId"] for span in spans}
    assert {len(span["traceId"]) for span in spans} == {32} and {len(i) for i in ids} == {16}
    assert all(span["parentSpanId"] in ids for span in spans if span["parentSpanId"])
    assert sum(1 for span in spans if not span["parentSpanId"]) == 1
    for span in spans:
        assert int(span["endTimeUnixNano"]) >= int(span["startTimeUnixNano"]) > 1_700_000_000 * 10**9
    model = next(span for span in spans if span["kind"] == SPAN_KIND_CLIENT)
    attributes = {entry["key"]: entry["value"] for entry in model["attributes"]}
    assert model["name"] == "chat sonnet"
    assert attributes["gen_ai.operation.name"] == {"stringValue": "chat"}
    assert attributes["gen_ai.provider.name"] == {"stringValue": "anthropic"}
    assert attributes["gen_ai.request.model"] == {"stringValue": "sonnet"}
    assert attributes["gen_ai.usage.input_tokens"]["intValue"].isdigit()
    assert attributes["ordnung.llm.outcome"] == {"stringValue": "ok"}
    assert {span["kind"] for span in spans} == {SPAN_KIND_CLIENT, SPAN_KIND_INTERNAL}
    text = json.dumps(exported, ensure_ascii=False)
    assert "Finanzamt" not in text and "Income tax" not in text, "no names, only ids"


def test_otlp_any_values() -> None:
    assert any_value(3) == {"intValue": "3"} and any_value(True) == {"boolValue": True}
    assert any_value(1.5) == {"doubleValue": 1.5} and any_value(None) is None
    assert any_value(["a", None]) == {"arrayValue": {"values": [{"stringValue": "a"}]}}
    assert any_value({"b": 1, "a": None}) == {
        "kvlistValue": {"values": [{"key": "b", "value": {"intValue": "1"}}]}
    }


def test_a_letter_without_a_reading_exports_no_spans() -> None:
    assert to_otlp(DocumentTrace(doc_id="doc_1"))["resourceSpans"][0]["scopeSpans"][0]["spans"] == []


# --------------------------------------------------------------------------------------------------
# ordnung trace
# --------------------------------------------------------------------------------------------------


async def test_ordnung_trace_prints_json_and_otel_in_process(data_dir: Path, tmp_path: Path) -> None:
    doc_id = await _read_tax_letter(data_dir)
    plain = runner.invoke(app, ["trace", doc_id, "--data-dir", str(data_dir)])
    assert plain.exit_code == 0, plain.output
    trace = json.loads(plain.stdout)
    assert trace["doc_id"] == doc_id and trace["run"]["reading"] == 1
    assert plain.stdout.isascii(), "names reach the terminal escaped"

    target = tmp_path / "trace.json"
    otel = runner.invoke(app, ["trace", doc_id, "--otel", "-o", str(target), "--data-dir", str(data_dir)])
    assert otel.exit_code == 0, otel.output
    assert json.loads(target.read_text(encoding="utf-8"))["resourceSpans"][0]["scopeSpans"][0]["spans"]

    first = runner.invoke(app, ["trace", doc_id, "--reading", "1", "--data-dir", str(data_dir)])
    assert first.exit_code == 0 and json.loads(first.stdout)["run"]["reading"] == 1
    missing = runner.invoke(app, ["trace", doc_id, "--reading", "3", "--data-dir", str(data_dir)])
    assert missing.exit_code == 1 and "Reading 3 of this letter isn't kept (kept: 1)" in missing.output
    unknown = runner.invoke(app, ["trace", "doc_nothere", "--data-dir", str(data_dir)])
    assert unknown.exit_code == 1 and "There is no letter doc_nothere" in unknown.output
    empty = runner.invoke(app, ["trace", doc_id, "--data-dir", str(tmp_path / "nothing")])
    assert empty.exit_code == 1 and "There is no Ordnung data" in empty.output


class _TraceApi(BaseHTTPRequestHandler):
    """A running server's trace route (the CLI's client side)."""

    server: _TraceServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self.server.paths.append(self.path)
        known = f"/api/documents/{self.server.trace.doc_id}/trace"
        status, body = (
            (200, self.server.trace.model_dump_json()) if self.path.startswith(known) else (404, "{}")
        )
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _TraceServer(ThreadingHTTPServer):
    def __init__(self, trace: DocumentTrace) -> None:
        super().__init__(("127.0.0.1", 0), _TraceApi)
        self.trace = trace
        self.paths: list[str] = []


async def test_ordnung_trace_asks_the_running_server(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = await _read_tax_letter(data_dir)
    with Store.open(Paths(data_dir)) as store:
        trace = document_trace(store, doc_id)
    server = _TraceServer(trace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        info = ServerInfo(port=server.server_address[1], pid=1, token="t")
        monkeypatch.setattr(cli, "reachable_server", lambda data: info)
        result = runner.invoke(app, ["trace", doc_id, "--otel", "--data-dir", str(tmp_path / "elsewhere")])
    finally:
        server.shutdown()
        server.server_close()
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert server.paths == [f"/api/documents/{doc_id}/trace"]


# --------------------------------------------------------------------------------------------------
# migration 0004
# --------------------------------------------------------------------------------------------------


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_0004_on_an_empty_database(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "empty.db", isolation_level=None)
    try:
        assert migrate(conn) == latest_version() >= 4
        assert {"id", "trace_id", "doc_id", "job_id", "parent_id", "key", "kind", "attributes"} <= _columns(
            conn, "trace_spans"
        )
        added = {"request_key", "prompt_name", "prompt_version", "served_model", "job_id", "stage", "span_id"}
        assert added | {"repair_of", "outcome"} <= _columns(conn, "llm_calls")
    finally:
        conn.close()


def test_0004_keeps_older_usage_rows_and_marks_failed_calls(tmp_path: Path) -> None:
    only_first = tmp_path / "m"
    only_first.mkdir()
    shutil.copy(MIGRATIONS_DIR / "0001_initial.sql", only_first / "0001_initial.sql")
    conn = sqlite3.connect(tmp_path / "old.db", isolation_level=None)
    try:
        assert migrate(conn, directory=only_first) == 1
        for ok in (1, 0):
            conn.execute(
                "INSERT INTO llm_calls (ts, purpose, model, backend, ok) VALUES ('2026-09-01T10:00:00Z', 'extract', "
                "'sonnet', 'claude', ?)",
                (ok,),
            )
        assert migrate(conn) == latest_version()
        rows = conn.execute("SELECT ok, outcome, request_key, span_id FROM llm_calls ORDER BY id").fetchall()
        assert rows == [(1, "ok", None, None), (0, "failed", None, None)]
    finally:
        conn.close()


def test_the_prebuilt_demo_has_a_trace_for_every_letter(tmp_path: Path) -> None:
    if not (DEFAULT_SNAPSHOT / "ordnung.db").is_file():
        pytest.skip("no demo snapshot in this checkout")
    copy = tmp_path / "demo"
    copy.mkdir()
    shutil.copy(DEFAULT_SNAPSHOT / "ordnung.db", copy / "ordnung.db")
    with Store.open(Paths(copy)) as store:
        assert store.schema_version == latest_version()
        documents = store.list_documents()
        assert documents
        for document in documents:
            trace = document_trace(store, document.id)
            assert trace.run is not None, document.id
            assert trace.run.timing == "recorded" and trace.run.model_calls >= 1
