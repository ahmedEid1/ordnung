"""Ledger and system endpoints: contracts (dates computed on read), parties, threads, timeline,
lanes, Ideas and the review, the brief, profile/settings/onboarding, catalog, jobs, usage, the
demo endpoints and the OpenAPI document."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import GYM_CONTRACT_LETTER, TAX_LETTER
from ordnung import clock
from ordnung.api.routes import demo as demo_routes
from ordnung.api.routes.profile import inbox_dir_problem
from ordnung.config import Paths
from ordnung.llm.replay import ReplayBackend
from ordnung.models import Document, Job, MailTrayItem, PartyDetail, Suggestion, TourState
from ordnung.secretary.brief import brief_key
from test_api_support import TODAY, Api, api_for

IDEA = {
    "kind": "saving",
    "title": "Compare phone tariffs",
    "body": "Your phone contract costs more than similar offers.",
    "fingerprint": "test:idea:1",
    "source": "rule",
    "rule_id": "test_rule",
}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _letter(api: Api, data: bytes) -> str:
    body = await api.upload(("letter.pdf", data))
    await api.read_all()
    return str(body["documents"][0]["id"])


# --------------------------------------------------------------------------------------------------
# contracts, parties, threads, timeline, lanes
# --------------------------------------------------------------------------------------------------


async def test_contracts_are_computed_on_read_and_can_be_corrected(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        await _letter(api, GYM_CONTRACT_LETTER.pdf())
        (contract,) = (await api.client.get("/api/contracts")).json()
        assert contract["name"] == "Muster Fitness membership"
        assert contract["computed"]["regime"] == "bgb309_new"
        assert contract["computed"]["earliest_exit"] == "2026-11-01"  # computed for today, not stored
        assert (await api.client.get("/api/contracts", params={"status": "ended"})).json() == []

        url = f"/api/contracts/{contract['id']}"
        updated = await api.client.patch(url, json={"cost_amount": 34.9, "notice_value": 2})
        assert updated.status_code == 200
        assert updated.json()["cost_amount"] == 34.9 and updated.json()["computed"] is not None
        for bad in ({"notice_unit": "fortnights"}, {"id": "ctr_x"}, {"start_date": "01.03.2024"}):
            assert (await api.client.patch(url, json=bad)).status_code == 422, bad
        assert (await api.client.patch("/api/contracts/ctr_unknown", json={"name": "x"})).status_code == 404

        dashboard = (await api.client.get("/api/dashboard")).json()
        assert dashboard["money"]["fixed_costs_monthly"] == 34.9


async def test_parties_threads_timeline_and_lanes(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _letter(api, TAX_LETTER.pdf())
        (party,) = (await api.client.get("/api/parties")).json()
        response = await api.client.get(f"/api/parties/{party['id']}")
        detail = PartyDetail.model_validate(response.json())
        assert [doc.id for doc in detail.documents] == [doc_id]
        assert len(detail.items) == 2 and len(detail.cases) == 1
        assert (await api.client.get("/api/parties/pty_unknown")).status_code == 404

        case = (await api.client.get(f"/api/cases/{detail.cases[0].id}")).json()
        assert set(case) == {"case", "party", "documents", "items", "drafts"}
        assert case["party"]["id"] == party["id"] and [d["id"] for d in case["documents"]] == [doc_id]
        assert (await api.client.get("/api/cases/cas_unknown")).status_code == 404

        timeline = (await api.client.get("/api/timeline")).json()
        assert {"document", "deadline", "payment"} <= {entry["type"] for entry in timeline}
        october = (
            await api.client.get("/api/timeline", params={"from": "2026-10-01", "to": "2026-10-31"})
        ).json()
        assert october and all("2026-10-01" <= entry["date"] <= "2026-10-31" for entry in october)
        bad = await api.client.get("/api/timeline", params={"from": "2026-10-31", "to": "2026-10-01"})
        assert bad.status_code == 422
        assert (await api.client.get("/api/timeline", params={"from": "soon"})).status_code == 422

        lanes = (await api.client.get("/api/lanes")).json()
        assert "tax" in {lane["id"] for lane in lanes}


# --------------------------------------------------------------------------------------------------
# Ideas, review, brief
# --------------------------------------------------------------------------------------------------


async def test_answering_ideas(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        idea = api.ctx.store.upsert_suggestion(IDEA)
        url = f"/api/suggestions/{idea.id}"
        assert [entry["id"] for entry in (await api.client.get("/api/suggestions")).json()] == [idea.id]

        dismissed = (await api.client.patch(url, json={"status": "dismissed"})).json()
        assert dismissed["status"] == "dismissed"
        snoozed = (await api.client.patch(url, json={"status": "snoozed"})).json()
        assert snoozed["snoozed_until"] == "2026-10-02"
        until = (
            await api.client.patch(url, json={"status": "snoozed", "snoozed_until": "2026-11-01"})
        ).json()
        assert until["snoozed_until"] == "2026-11-01"
        undone = (await api.client.patch(url, json={"status": "new", "snoozed_until": None})).json()
        assert (undone["status"], undone["snoozed_until"]) == ("new", None)
        assert (await api.client.patch(url, json={"status": "expired"})).status_code == 422
        assert (
            await api.client.patch("/api/suggestions/sug_unknown", json={"status": "done"})
        ).status_code == 404

        api.ctx.store.update_suggestion(idea.id, status="expired")
        assert (await api.client.get("/api/suggestions")).json() == []
        assert len((await api.client.get("/api/suggestions", params={"status": "expired"})).json()) == 1


async def test_review_runs_in_the_background(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        await _letter(api, TAX_LETTER.pdf())
        started = await api.client.post("/api/suggestions/review")
        assert started.status_code == 202 and started.json() == {"started": True, "running": True}
        state = api.app.state.ordnung
        await state.background.wait("review")
        assert "review" in [call.purpose for call in api.backend.calls]
        assert api.ctx.store.get_meta("last_review_at") == TODAY


async def test_review_is_refused_with_recorded_answers_only(data_dir: Path, tmp_path: Path) -> None:
    async with api_for(data_dir) as api:
        api.ctx.llm.backend = ReplayBackend(tmp_path / "fixtures")
        refused = await api.client.post("/api/suggestions/review")
        assert refused.status_code == 503 and "recorded" in refused.json()["detail"]


async def test_brief_get_is_side_effect_free_and_post_regenerates(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        await _letter(api, TAX_LETTER.pdf())
        first = (await api.client.get("/api/brief")).json()
        assert first["source"] == "template" and first["date"] == TODAY and first["text"]
        assert first["generated_at"] is None
        assert api.ctx.store.get_meta(brief_key(clock.today())) is None  # GET stored nothing

        regenerated = await api.client.post("/api/brief")
        assert regenerated.status_code == 200
        assert regenerated.json()["source"] == "llm"
        assert regenerated.json()["text"] == "Good morning. Nothing urgent today."
        assert (await api.client.get("/api/brief")).json() == regenerated.json()


# --------------------------------------------------------------------------------------------------
# profile, settings, onboarding
# --------------------------------------------------------------------------------------------------


async def test_profile_is_merged_and_validated(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        updated = await api.client.put("/api/profile", json={"name": "Sam Rivera", "region": "by"})
        assert updated.status_code == 200
        assert (updated.json()["name"], updated.json()["region"], updated.json()["language"]) == (
            "Sam Rivera",
            "BY",
            "en",
        )
        for bad in (
            {"region": "Atlantis"},
            {"timezone": "Mars/Olympus"},
            {"postal_buffer_days": -1},
            {"shoe": 42},
        ):
            assert (await api.client.put("/api/profile", json=bad)).status_code == 422, bad
        assert (await api.client.get("/api/profile")).json()["region"] == "BY"


async def test_settings_are_merged_and_the_inbox_is_guarded(data_dir: Path, tmp_path: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.put(
            "/api/settings", json={"models": {"extract": "opus"}, "concurrency": 3}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["models"]["extract"] == "opus" and body["models"]["brief"] == "haiku"
        assert body["concurrency"] == 3 and api.ctx.settings.concurrency == 3

        inbox = tmp_path / "scans"
        ok = await api.client.put("/api/settings", json={"inbox_dir": str(inbox)})
        assert ok.json()["inbox_dir"] == str(inbox.resolve())
        for bad in (
            "/",
            str(Path.home()),
            str(data_dir),
            str(data_dir.parent),
            str(data_dir / "files" / "x"),
            "relative/dir",
        ):
            rejected = await api.client.put("/api/settings", json={"inbox_dir": bad})
            assert rejected.status_code == 422, bad
        cleared = await api.client.put("/api/settings", json={"inbox_dir": None})
        assert cleared.json()["inbox_dir"] is None

        assert (await api.client.put("/api/settings", json={"demo": True})).status_code == 422
        assert (
            await api.client.put("/api/settings", json={"simulated_today": "2030-01-01"})
        ).status_code == 422
        assert (await api.client.put("/api/settings", json={**body, "inbox_dir": None})).status_code == 200


def test_inbox_folder_rules(tmp_path: Path) -> None:
    paths = Paths(tmp_path / "data").ensure()
    assert inbox_dir_problem(str(tmp_path / "scans"), paths) is None
    assert inbox_dir_problem(str(paths.inbox), paths) is None
    assert inbox_dir_problem(str(tmp_path), paths) is not None
    assert inbox_dir_problem(str(paths.derived), paths) is not None


async def test_onboarding_marks_the_profile_and_can_skip_ai(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.post(
            "/api/onboarding", json={"profile": {"name": "Sam Rivera", "region": "NW"}, "skip_ai": True}
        )
        assert response.status_code == 200
        assert response.json()["onboarded"] is True and response.json()["name"] == "Sam Rivera"
        assert (await api.client.get("/api/settings")).json()["llm_brief"] is False


# --------------------------------------------------------------------------------------------------
# catalog, jobs, privacy
# --------------------------------------------------------------------------------------------------


async def test_rules_jobs_activity_and_usage(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        rules = (await api.client.get("/api/rules")).json()
        assert rules and {"id", "title", "citation", "summary"} <= set(rules[0])
        doc_id = await _letter(api, TAX_LETTER.pdf())

        jobs = (await api.client.get("/api/jobs")).json()
        assert [(job["doc_id"], job["status"]) for job in jobs] == [(doc_id, "done")]
        assert (await api.client.get("/api/jobs", params={"active_only": "true"})).json() == []

        activity = (await api.client.get("/api/activity", params={"limit": 5})).json()
        assert {"document.added", "document.processed"} <= {entry["kind"] for entry in activity}
        usage = (await api.client.get("/api/usage")).json()
        assert usage["calls"] >= 1 and "extract" in usage["by_purpose"]
        assert usage["recent"][0]["doc_ids"] == [doc_id]


# --------------------------------------------------------------------------------------------------
# demo endpoints
# --------------------------------------------------------------------------------------------------


def _fake_demo_module(monkeypatch: pytest.MonkeyPatch, api: Api) -> dict[str, Any]:
    tour = TourState()
    opened: dict[str, Any] = {}

    def get_tour(store: object) -> TourState:
        return tour

    def update_tour(store: object, **changes: Any) -> TourState:
        nonlocal tour
        tour = tour.model_copy(update=changes)
        return tour

    def list_mail(ctx: object) -> list[MailTrayItem]:
        return [
            MailTrayItem(
                id="mail_1", filename="a.pdf", sender="Stadt", subject="Hello", kind_hint="authority"
            )
        ]

    async def open_mail(ctx: object, mail_id: str) -> tuple[Document, Job]:
        if mail_id != "mail_1":
            raise KeyError(mail_id)
        document = api.ctx.store.add_document(
            sha256="c" * 64, filename="a.pdf", mime="application/pdf", file_path="x"
        )
        job = api.ctx.store.enqueue_job("ingest", document.id)
        opened["doc_id"] = document.id
        return document, job

    def suggested_questions() -> list[str]:
        return ["What do I have to pay?", "When does my phone contract end?"]

    module = types.ModuleType("ordnung_test_demo")
    for function in (get_tour, update_tour, list_mail, open_mail, suggested_questions):
        setattr(module, function.__name__, function)
    monkeypatch.setitem(sys.modules, "ordnung_test_demo", module)
    monkeypatch.setattr(demo_routes, "DEMO_MODULES", ("ordnung_test_demo_missing", "ordnung_test_demo"))
    return opened


async def test_demo_endpoints(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with api_for(data_dir) as api:
        assert (await api.client.get("/api/demo/tour")).status_code == 404  # not a demo server

    async with api_for(data_dir, demo=True) as api:
        monkeypatch.setattr(demo_routes, "DEMO_MODULES", ("ordnung_test_demo_missing",))
        assert (await api.client.get("/api/demo/mail")).status_code == 503

        opened = _fake_demo_module(monkeypatch, api)
        assert (await api.client.get("/api/demo/tour")).json() == {
            "active": False,
            "step": 0,
            "completed": False,
        }
        moved = await api.client.patch("/api/demo/tour", json={"active": True, "step": 2})
        assert moved.json() == {"active": True, "step": 2, "completed": False}
        assert (await api.client.patch("/api/demo/tour", json={"step": -1})).status_code == 422

        (mail,) = (await api.client.get("/api/demo/mail")).json()
        assert mail["id"] == "mail_1" and mail["opened"] is False
        result = (await api.client.post("/api/demo/mail", json={"id": "mail_1"})).json()
        assert result["document"]["id"] == opened["doc_id"] and result["job"]["doc_id"] == opened["doc_id"]
        assert (await api.client.post("/api/demo/mail", json={"id": "mail_9"})).status_code == 404
        # the Ask chips are the demo's recorded questions, word for word
        questions = (await api.client.get("/api/demo/questions")).json()
        assert questions == ["What do I have to pay?", "When does my phone contract end?"]
        health = (await api.client.get("/api/health")).json()
        assert health["demo"] is True


# --------------------------------------------------------------------------------------------------
# OpenAPI
# --------------------------------------------------------------------------------------------------


async def test_openapi_lists_view_models_and_the_ask_stream(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        schema = (await api.client.get("/api/openapi.json")).json()
        components = schema["components"]["schemas"]
        for name in (
            "Dashboard",
            "TimelineEntry",
            "Lane",
            "LaneBar",
            "DocumentDetail",
            "PartyDetail",
            "CaseDetail",
            "UsageStats",
            "Health",
            "RuleInfo",
            "TourState",
            "MailTrayItem",
            "SearchHit",
            "StreamEvent",
        ):
            assert name in components, name
        ask = schema["paths"]["/api/ask"]["post"]["responses"]["200"]["content"]
        assert ask == {"text/event-stream": {"schema": {"$ref": "#/components/schemas/StreamEvent"}}}
        assert set(components["StreamEvent"]["properties"]) >= {"type", "text", "citations", "thread_id"}
        assert "/api/documents/{doc_id}" in schema["paths"]
        assert Suggestion.__name__ in components


async def test_real_demo_package_serves_tour_and_tray(data_dir: Path) -> None:
    pytest.importorskip("ordnung.demo.tour")
    async with api_for(data_dir, demo=True) as api:
        assert (await api.client.get("/api/demo/tour")).json() == {
            "active": False,
            "step": 0,
            "completed": False,
        }
        moved = await api.client.patch("/api/demo/tour", json={"active": True, "step": 1})
        assert moved.json() == {"active": True, "step": 1, "completed": False}
        assert (await api.client.get("/api/demo/tour")).json()["step"] == 1
        tray = (await api.client.get("/api/demo/mail")).json()
        assert tray and all(entry["opened"] is False for entry in tray)
        unknown = await api.client.post("/api/demo/mail", json={"id": "no-such-letter"})
        assert unknown.status_code == 404
