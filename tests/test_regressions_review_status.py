"""The "Please check" status after reading a letter again (round 2, R2-REV-1).

dates.py defines the rule: "a letter is 'Please check' exactly while one of its open to-dos still needs
checking (confirmed, re-dated, dismissed, done or deleted ones don't)", and plan.py keeps what the
person did on a re-read. But ``write_plan`` used to set the status from the fresh reading alone
(``Verification.needs_review``), so Reprocess brought "Please check" back for a letter whose only
unsure to-do was already paid or confirmed.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TAX_LETTER
from ordnung import clock
from test_api_support import TODAY, Api, ApiRouter, api_for

UNFOUND_QUOTE = "Bitte überweisen Sie 1.234,56 EUR bis 15.10.2026 auf unser Konto."  # not on the page


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def _router() -> ApiRouter:
    router = ApiRouter()
    payment = next(i for i in router.payloads[TAX_LETTER.marker]["items"] if i["kind"] == "payment")
    payment["quote"] = UNFOUND_QUOTE  # the payment's sentence can't be found: "Please check"
    return router


async def _letter(api: Api) -> tuple[str, dict[str, Any]]:
    body = await api.upload(("letter.pdf", TAX_LETTER.pdf()))
    await api.read_all()
    doc_id = body["documents"][0]["id"]
    detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
    assert detail["document"]["status"] == "needs_review"
    payment = next(item for item in detail["items"] if item["kind"] == "payment")
    assert payment["grounding"] == "unverified"
    return doc_id, payment


async def _status_after_reprocess(api: Api, doc_id: str) -> str:
    assert (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]["status"] == "processed"
    await api.client.post(f"/api/documents/{doc_id}/reprocess")
    await api.read_all()
    return str((await api.client.get(f"/api/documents/{doc_id}")).json()["document"]["status"])


async def test_reprocess_keeps_a_letter_checked_when_its_unsure_to_do_is_done(data_dir: Path) -> None:
    """The unsure payment is already done, so per refresh_review_status nothing needs checking — the
    status after Reprocess comes from the stored to-dos, not the new reading alone."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id, payment = await _letter(api)
        assert (
            await api.client.patch(f"/api/items/{payment['id']}", json={"status": "done"})
        ).status_code == 200
        assert await _status_after_reprocess(api, doc_id) == "processed"


async def test_reprocess_keeps_a_letter_checked_when_its_unsure_to_do_was_confirmed(data_dir: Path) -> None:
    """'Yes, that's right' (grounding=user, kept on re-read as user_modified) survives Reprocess: the
    letter is not marked 'Please check' again from the fresh reading."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id, payment = await _letter(api)
        assert (await api.client.post(f"/api/items/{payment['id']}/confirm")).status_code == 200
        assert await _status_after_reprocess(api, doc_id) == "processed"
