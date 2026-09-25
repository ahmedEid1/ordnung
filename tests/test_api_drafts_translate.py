"""“Re-translate” (``POST /api/drafts/{id}/translate``): after the person edits the German letter, the
model translates the letter as it now stands (purpose ``draft``) — only the translation changes. The
zero-token demo refuses with a 409, letters about private documents and model failures are refused
with a clear message."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import TAX_LETTER
from ordnung import clock
from ordnung.api.app import create_app
from ordnung.api.routes.drafts import DEMO_TRANSLATE_MESSAGE
from ordnung.app_context import build_context
from ordnung.llm.base import ClaudeTimeout
from ordnung.llm.replay import ReplayBackend
from ordnung.llm.schemas import draft_translation_schema
from test_api_support import TODAY, Api, ApiRouter, api_for, client_for

NEW_TRANSLATION = (
    "Subject: Objection\n\nDear Sir or Madam,\n\nI object. I also moved house.\n\nYours faithfully"
)


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _objection(api: Api) -> dict[str, object]:
    await api.upload(("letter.pdf", TAX_LETTER.pdf()))
    await api.read_all()
    doc_id = (await api.client.get("/api/documents")).json()[0]["id"]
    created = await api.client.post("/api/drafts", json={"kind": "objection", "doc_id": doc_id})
    assert created.status_code == 201, created.text
    return dict(created.json())


async def test_retranslate_translates_the_edited_letter(data_dir: Path) -> None:
    router = ApiRouter()
    async with api_for(data_dir, router=router) as api:
        draft = await _objection(api)
        edited_body = f"{draft['body']}\n\nAußerdem bin ich umgezogen."
        edited = await api.client.patch(f"/api/drafts/{draft['id']}", json={"body": edited_body})
        assert edited.status_code == 200
        router.answers["draft"] = {"body_translation": f"  {NEW_TRANSLATION}\n"}
        calls_before = len(api.backend.calls)

        response = await api.client.post(f"/api/drafts/{draft['id']}/translate")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["body_translation"] == NEW_TRANSLATION
        assert body["body"] == edited_body and body["subject"] == draft["subject"]
        assert body["checks"] == edited.json()["checks"]
        (call,) = api.backend.calls[calls_before:]
        assert call.purpose == "draft"
        assert call.schema_ == draft_translation_schema()
        assert "Translation language: English" in call.prompt
        # the letter as it now stands, as untrusted data
        untrusted = call.prompt.split("<untrusted_document>")[1].split("</untrusted_document>")[0]
        assert "umgezogen" in untrusted and str(draft["subject"]) in untrusted
        stored = (await api.client.get(f"/api/drafts/{draft['id']}")).json()
        assert stored["body_translation"] == NEW_TRANSLATION
        activity = (await api.client.get("/api/activity")).json()
        assert any(entry["kind"] == "draft.translated" for entry in activity)


async def test_retranslate_refusals(data_dir: Path) -> None:
    router = ApiRouter()
    async with api_for(data_dir, router=router) as api:
        assert (await api.client.post("/api/drafts/drf_missing/translate")).status_code == 404
        draft = await _objection(api)

        router.answers["draft"] = {"body_translation": "   "}
        unreadable = await api.client.post(f"/api/drafts/{draft['id']}/translate")
        assert unreadable.status_code == 503
        assert unreadable.json()["code"] == "llm_bad_output"

        router.errors["draft"] = lambda: ClaudeTimeout("Claude took too long to answer.")
        failed = await api.client.post(f"/api/drafts/{draft['id']}/translate")
        assert failed.status_code == 503 and failed.json()["code"] == "llm_timeout"
        assert (await api.client.get(f"/api/drafts/{draft['id']}")).json()["body_translation"] == draft[
            "body_translation"
        ]

        # a letter already in the person's language has nothing to translate
        english = api.ctx.store.add_draft(kind="general_reply", language="en", body="Dear Sir or Madam,")
        same = await api.client.post(f"/api/drafts/{english.id}/translate")
        assert same.status_code == 422 and "already in your language" in same.json()["detail"]

        # letters about a private document never go to the model
        doc_id = str(draft["doc_id"])
        api.ctx.store.update_document(doc_id, ai_private=True)
        del router.errors["draft"]
        calls_before = len(api.backend.calls)
        private = await api.client.post(f"/api/drafts/{draft['id']}/translate")
        assert private.status_code == 422 and "private" in private.json()["detail"]
        assert len(api.backend.calls) == calls_before


async def test_the_demo_cannot_retranslate(tmp_path: Path) -> None:
    ctx = build_context(tmp_path / "demo", backend_obj=ReplayBackend(tmp_path / "fixtures"))
    try:
        draft = ctx.store.add_draft(kind="general_reply", body="Sehr geehrte Damen und Herren,")
        app = create_app(ctx, token=None, demo=True)
        async with client_for(app) as client:
            refused = await client.post(f"/api/drafts/{draft.id}/translate")
            assert refused.status_code == 409
            assert refused.json()["detail"] == DEMO_TRANSLATE_MESSAGE
            assert "ordnung serve" in DEMO_TRANSLATE_MESSAGE
            assert (await client.post("/api/drafts/drf_missing/translate")).status_code == 404
    finally:
        ctx.close()
