"""End to end: every GET endpoint answers what the OpenAPI schema promises.

An app on a FakeBackend context is seeded with real reading (a tax assessment and a gym contract),
a draft, an Ask thread, a calendar export and a brief; then every GET route of the API is called
the way the web app calls it and each JSON body is validated against the response schema of
``app.openapi()`` (non-JSON routes are checked for their content type). A new GET route fails the
coverage check until it is added here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from fake_caldav import MemorySecrets
from fixtures_llm import GYM_CONTRACT_LETTER, TAX_LETTER
from ordnung import clock
from ordnung.api.routes import calendar_sync, sync
from test_api_support import TODAY, Api, api_for, sse_messages

NOT_CALLED = {
    "/api/events": "an endless event stream (tested in test_api_ledger)",
    "/api/documents.zip": "not written yet: answers 501 until the export lands",
}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


class Contract:
    """Validates responses against the app's OpenAPI schema and records which routes were hit."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.hit: set[str] = set()
        self.problems: list[str] = []

    def operation(self, method: str, path: str) -> tuple[str, dict[str, Any]]:
        templates = [
            template
            for template in self.schema["paths"]
            if re.fullmatch(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)), path)
        ]
        templates.sort(key=lambda t: (t.count("{"), -len(re.sub(r"\{[^}]+\}", "", t))))
        for template in templates:
            operation = self.schema["paths"][template].get(method)
            if operation is not None:
                return template, operation
        raise AssertionError(f"{method.upper()} {path} is not in the OpenAPI schema")

    def validator(self, body_schema: dict[str, Any]) -> Draft202012Validator:
        return Draft202012Validator({**body_schema, "components": self.schema["components"]})

    def check_json(self, method: str, path: str, status: int, body: Any) -> None:
        template, operation = self.operation(method, path)
        self.hit.add(template)
        declared = operation["responses"].get(str(status))
        if declared is None:
            self.problems.append(f"{method.upper()} {path}: status {status} is not declared")
            return
        body_schema = declared.get("content", {}).get("application/json", {}).get("schema")
        if body_schema is None:
            self.problems.append(f"{method.upper()} {path}: {status} has no JSON schema")
            return
        for error in self.validator(body_schema).iter_errors(body):
            where = "/".join(str(part) for part in error.absolute_path)
            self.problems.append(f"{method.upper()} {path} → {where or '(root)'}: {error.message[:200]}")


async def _get(api: Api, contract: Contract, path: str, **params: Any) -> Any:
    response = await api.client.get(path, params=params or None)
    assert response.status_code == 200, f"GET {path}: {response.status_code} {response.text[:300]}"
    body = response.json()
    contract.check_json("get", path, 200, body)
    return body


async def _get_file(api: Api, contract: Contract, path: str, media_type: str) -> None:
    response = await api.client.get(path)
    assert response.status_code == 200, f"GET {path}: {response.status_code} {response.text[:300]}"
    assert response.headers["content-type"].startswith(media_type), (path, response.headers["content-type"])
    contract.hit.add(contract.operation("get", path)[0])


async def _seed(api: Api, contract: Contract) -> dict[str, str]:
    """Letters read by the fake model, a contract, a draft, an Ask thread, an export and a brief."""
    client = api.client
    upload = await client.post(
        "/api/documents",
        files=[
            ("files", ("bescheid.pdf", TAX_LETTER.pdf())),
            ("files", ("vertrag.pdf", GYM_CONTRACT_LETTER.pdf())),
        ],
        data={"combine": "false", "private": "false"},
    )
    assert upload.status_code == 201, upload.text
    contract.check_json("post", "/api/documents", 201, upload.json())
    assert await api.read_all() == 2
    tax_id = upload.json()["documents"][0]["id"]

    items = (await client.get("/api/items")).json()
    contracts = (await client.get("/api/contracts")).json()
    assert items and contracts, "the fake reading should produce to-dos and a contract"

    draft = await client.post("/api/drafts", json={"kind": "cancellation", "contract_id": contracts[0]["id"]})
    assert draft.status_code == 201, draft.text
    contract.check_json("post", "/api/drafts", 201, draft.json())
    sent = await client.post(
        f"/api/drafts/{draft.json()['id']}/sent",
        json={"channel": "registered_letter", "date": TODAY, "tracking_number": "RT123456785DE"},
    )
    contract.check_json("post", f"/api/drafts/{draft.json()['id']}/sent", 200, sent.json())
    call = await client.post(
        "/api/calls",
        json={
            "party_id": contracts[0]["party_id"],
            "called_on": TODAY,
            "summary": "They will send the confirmation.",
            "promise": "Written confirmation",
            "promise_due": "2026-10-05",
        },
    )
    contract.check_json("post", "/api/calls", 201, call.json())

    ask = await client.post("/api/ask", json={"question": "Is anything due?"})
    events = [json.loads(message["data"]) for message in sse_messages(ask.text)]
    stream_schema = {"$ref": "#/components/schemas/StreamEvent"}
    for event in events:
        for error in contract.validator(stream_schema).iter_errors(event):
            contract.problems.append(f"POST /api/ask event {event.get('type')}: {error.message[:200]}")
    done = events[-1]
    assert done["type"] == "done" and done["thread_id"], events

    exported = await client.post("/api/calendar/exported")
    contract.check_json("post", "/api/calendar/exported", 200, exported.json())
    brief = await client.post("/api/brief")
    contract.check_json("post", "/api/brief", 200, brief.json())
    review = await client.post("/api/suggestions/review")
    contract.check_json("post", "/api/suggestions/review", review.status_code, review.json())
    return {
        "doc": tax_id,
        "item": items[0]["id"],
        "party": contracts[0]["party_id"] or items[0]["party_id"],
        "case": (await client.get(f"/api/documents/{tax_id}")).json()["document"]["case_id"],
        "draft": draft.json()["id"],
        "thread": done["thread_id"],
    }


async def _hand_off_sync(contract: Contract, data_dir: Path, folder: Path) -> None:
    """The demo never syncs: hand-off sync's GETs on a computer that does (the fake engine), with
    another computer and a kept copy."""
    from sync_fake_engine import FakeEngine, FakeSession
    from sync_support import computer, connect

    engine = FakeEngine()
    async with (
        computer(data_dir / "desk", engine=engine) as desk,
        computer(data_dir / "lap", engine=engine) as lap,
    ):
        await connect(desk, folder, "desktop")
        await connect(lap, folder, "laptop")
        kept = FakeSession(engine, lap.ctx.paths).keep_local(
            lap.ctx.paths, "before you kept desktop's Ordnung"
        )
        await lap.app.state.ordnung.sync.load()
        found = await _get(lap, contract, "/api/sync")
        assert found["connected"] and len(found["computers"]) == 2 and found["kept"]
        await _get_file(lap, contract, f"/api/sync/kept/{kept.name}", "application/octet-stream")


async def test_every_get_endpoint_matches_the_openapi_schema(data_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "Nextcloud").mkdir()
    async with api_for(data_dir, demo=True) as api:
        contract = Contract(api.app.openapi())
        ids = await _seed(api, contract)
        assert all(ids.values()), ids

        # what the web app loads, page by page
        await _get(api, contract, "/api/health")
        await _get(api, contract, "/api/profile")
        await _get(api, contract, "/api/settings")
        await _get(api, contract, "/api/folder")
        await _get(api, contract, "/api/dashboard")
        await _get(api, contract, "/api/brief")
        await _get(api, contract, "/api/documents")
        await _get(api, contract, "/api/documents", q="Einkommensteuer", limit=8)
        detail = await _get(api, contract, f"/api/documents/{ids['doc']}")
        assert detail["items"] and detail["pages"]
        await api.client.post(f"/api/documents/{ids['doc']}/reprocess")
        assert await api.read_all() == 1
        trace = await _get(api, contract, f"/api/documents/{ids['doc']}/trace")
        assert trace["run"]["reading"] == 2 and trace["spans"]
        await _get(api, contract, f"/api/documents/{ids['doc']}/trace/compare")
        await _get(api, contract, "/api/traces")
        await _get(api, contract, "/api/items", status="open", include_undated="true")
        await _get(api, contract, f"/api/items/{ids['item']}")
        await _get(api, contract, "/api/contracts")
        await _get(api, contract, "/api/parties")
        await _get(api, contract, f"/api/parties/{ids['party']}")
        await _get(api, contract, f"/api/cases/{ids['case']}")
        await _get(api, contract, "/api/timeline", **{"from": "2026-01-01", "to": "2026-12-31"})
        await _get(api, contract, "/api/lanes")
        numbers = await _get(api, contract, "/api/numbers")
        assert numbers["organisations"], "the tax office and the gym get a call sheet"
        week = await _get(api, contract, "/api/week")
        assert len(week["steps"]) == 7
        await _get(api, contract, "/api/suggestions")
        await _get(api, contract, f"/api/chat/{ids['thread']}")
        await _get(api, contract, "/api/drafts")
        await _get(api, contract, f"/api/drafts/{ids['draft']}")
        proof = await _get(api, contract, f"/api/drafts/{ids['draft']}/proof")
        assert proof["sent"] and proof["tracking"]["checked"]
        waiting = await _get(api, contract, "/api/waiting")
        assert {entry["source"] for entry in waiting} >= {"letter", "call"}
        await _get(api, contract, "/api/calls", party_id=ids["party"])
        await _get(api, contract, "/api/activity", limit=50)
        assert await _get(api, contract, "/api/activity", device="phn_000000000000") == []
        usage = await _get(api, contract, "/api/usage")
        assert usage["by_purpose"], "the fake reading is accounted per purpose"
        await _get(api, contract, "/api/rules")
        await _get(api, contract, "/api/jobs", active_only="false")
        await _get(api, contract, "/api/reminders/desktop")
        await _get(api, contract, "/api/backup")
        api.app.dependency_overrides[calendar_sync.get_secrets] = lambda: (
            MemorySecrets()
        )  # not the real keyring
        await _get(api, contract, "/api/calendar/sync")
        await _get(api, contract, "/api/calendar/sync/preview", mode="full")
        phone = await _get(api, contract, "/api/phone")
        assert phone["available"] is False and phone["devices"] == []  # never in the demo
        api.app.dependency_overrides[sync.get_secrets] = lambda: MemorySecrets()  # not the real keyring
        hand_off = await _get(api, contract, "/api/sync")
        assert hand_off["available"] is False and hand_off["mode"] == "off"  # the demo never syncs
        await _hand_off_sync(contract, tmp_path, tmp_path / "Nextcloud" / "Ordnung")
        await _get(api, contract, "/api/demo/tour")
        await _get(api, contract, "/api/demo/mail")
        await _get(api, contract, "/api/demo/questions")

        # files the pages link to
        await _get_file(api, contract, f"/api/documents/{ids['doc']}/file", "application/pdf")
        await _get_file(api, contract, f"/api/documents/{ids['doc']}/pages/1.jpg", "image/jpeg")
        await _get_file(api, contract, f"/api/documents/{ids['doc']}/thumbnail.jpg", "image/jpeg")
        await _get_file(api, contract, f"/api/items/{ids['item']}.ics", "text/calendar")
        await _get_file(api, contract, "/api/calendar.ics", "text/calendar")
        await _get_file(api, contract, f"/api/drafts/{ids['draft']}/pdf", "application/pdf")
        await _get_file(api, contract, f"/api/drafts/{ids['draft']}/preview.png", "image/png")
        await _get_file(api, contract, f"/api/drafts/{ids['draft']}/proof.pdf", "application/pdf")

        assert not contract.problems, "\n".join(contract.problems)
        get_routes = {path for path, operations in contract.schema["paths"].items() if "get" in operations}
        missing = sorted(get_routes - contract.hit - set(NOT_CALLED))
        assert not missing, f"GET routes without a contract check: {missing}"


async def test_health_probe_runs_the_doctor_once_a_minute(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        contract = Contract(api.app.openapi())
        first = await api.client.get("/api/health", params={"probe": "1"})
        assert first.status_code == 200, first.text
        contract.check_json("get", "/api/health", 200, first.json())
        checks = {check["id"]: check for check in first.json()["checks"]}
        # the fake backend never runs the claude CLI: the local checks only, zero tokens
        assert {"sqlite_fts", "data_dir", "disk"} <= set(checks) and not any(
            c.startswith("claude") for c in checks
        )
        again = await api.client.get("/api/health", params={"probe": "1"})
        assert again.status_code == 429 and int(again.headers["Retry-After"]) > 0
        assert "try again" in again.json()["detail"]
        plain = (await api.client.get("/api/health")).json()
        assert plain["checks"] == [] and plain["rules_last_checked"]
        assert not contract.problems, contract.problems


async def test_health_names_the_model_the_environment_pins(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ORDNUNG_CLAUDE_MODEL beats the saved model for every call while it is set, so health says so
    (Settings → Claude shows the pin next to the field); unset or empty, nothing is pinned."""
    monkeypatch.delenv("ORDNUNG_CLAUDE_MODEL", raising=False)
    async with api_for(data_dir) as api:
        assert (await api.client.get("/api/health")).json()["model_pinned"] is None
        monkeypatch.setenv("ORDNUNG_CLAUDE_MODEL", "claude-sonnet-5")
        assert (await api.client.get("/api/health")).json()["model_pinned"] == "claude-sonnet-5"
        monkeypatch.setenv("ORDNUNG_CLAUDE_MODEL", "")
        assert (await api.client.get("/api/health")).json()["model_pinned"] is None


async def test_health_probe_with_the_claude_cli_runs_the_live_check(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ordnung.api.routes import system
    from ordnung.doctor import DoctorReport
    from ordnung.models import ClaudeStatus, DoctorCheck

    calls: list[tuple[Path, bool, str | None]] = []

    async def fake_doctor(data: Path, *, probe: bool = False, model: str | None = None) -> DoctorReport:
        calls.append((data, probe, model))
        check = DoctorCheck(id="claude_probe", label="Live test call", status="ok", detail="Claude answered.")
        return DoctorReport(checks=[check], claude=ClaudeStatus(installed=True, version="2.1.4", ok=True))

    monkeypatch.setattr(system, "backend_uses_cli", lambda ctx: True)
    async with api_for(data_dir) as api:
        api.app.state.ordnung.doctor = fake_doctor
        # the live call runs on the model every call runs on: the one saved under Settings → Claude
        saved = await api.client.put("/api/settings", json={"model": "claude-opus-5-5"})
        assert saved.status_code == 200, saved.text
        probed = (await api.client.get("/api/health", params={"probe": "true"})).json()
        assert calls == [(api.ctx.paths.data_dir, True, "claude-opus-5-5")]
        assert probed["checks"][0]["id"] == "claude_probe" and probed["claude"]["ok"] is True
        # the fresh status is what the cached health shows from now on (no second probe)
        assert (await api.client.get("/api/health")).json()["claude"]["version"] == "2.1.4"
        assert len(calls) == 1
