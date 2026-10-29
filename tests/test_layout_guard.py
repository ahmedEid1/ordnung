"""An e-mail whose text Pillow can't lay out on a page is refused with a reason at every way in: upload, the
phone (the same route), the watched folder, ``ordnung add`` and proof of a sent letter. Never a server error or
a traceback (:mod:`ordnung.ingest.layout_guard`).

No character Ordnung knows of makes the layout fail any more: the paragraph separators that did are line
breaks now (``tests/test_text.py``). So the fixture ``unlaid`` makes the font fail the way raqm did, on a
private-use character, and these tests run the same on every system."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import ImageFont

from fixtures_llm import TODAY, Router, fake_backend
from ordnung import cli, clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import text
from ordnung.ingest.intake import IntakeError
from ordnung.ingest.layout_guard import UNLAID_TEXT, text_layout_refused
from test_api_proof import _sent
from test_api_support import api_for
from test_cli import invoke
from test_folder_watcher import eventually, logged, use_folder, watching

#: A private-use character the font stand-in fails on, as raqm did on a paragraph separator.
UNLAYABLE = "\ue000"
MAIL = (
    b"From: stadtwerke@example.org\r\nTo: sam@example.org\r\nSubject: Ihre Rechnung\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\nGuten "
    + UNLAYABLE.encode()
    + b"Tag,\r\nanbei Ihre Rechnung.\r\n"
)
#: Raised as if from Pillow's font module, as raqm's failure was.
FONT_ERROR = compile("raise RuntimeError('raqm_layout() failed.')", ImageFont.__file__, "exec")


class _LikeRaqm:
    """The bundled font, failing on :data:`UNLAYABLE` the way raqm failed on a paragraph separator."""

    def __init__(self, font: ImageFont.FreeTypeFont) -> None:
        self._font = font

    def getlength(self, line: str, *args: Any, **kwargs: Any) -> float:
        if UNLAYABLE in line:
            exec(FONT_ERROR)
        return self._font.getlength(line, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._font, name)


@pytest.fixture
def unlaid(monkeypatch: pytest.MonkeyPatch) -> None:
    real = text.text_font
    monkeypatch.setattr(text, "text_font", lambda: _LikeRaqm(real()))


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def _flat(output: str) -> str:
    return " ".join(output.split())


def test_only_pillows_font_failing_becomes_a_refusal() -> None:
    with pytest.raises(IntakeError) as refused, text_layout_refused():
        exec(FONT_ERROR)
    assert str(refused.value) == UNLAID_TEXT
    assert isinstance(refused.value.__cause__, RuntimeError)
    with pytest.raises(RuntimeError, match="something else"), text_layout_refused():
        raise RuntimeError("something else")
    with pytest.raises(ValueError, match="not this"), text_layout_refused():
        raise ValueError("not this")


async def test_an_uploaded_e_mail_whose_text_cant_be_laid_out_is_refused_with_the_reason(
    data_dir: Path, unlaid: None
) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.post("/api/documents", files=[("files", ("rechnung.eml", MAIL))])
        assert response.status_code == 422, response.text
        assert response.json()["errors"] == [{"filename": "rechnung.eml", "detail": UNLAID_TEXT}]
        assert api.ctx.store.list_documents() == []


async def test_a_proof_whose_text_cant_be_laid_out_is_refused_with_the_reason(
    data_dir: Path, unlaid: None
) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        response = await api.client.post(
            f"/api/drafts/{draft_id}/proofs",
            files={"file": ("gesendet.eml", MAIL)},
            data={"kind": "sent_email"},
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == UNLAID_TEXT


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    folder = tmp_path / "scans"
    folder.mkdir()
    return folder


@pytest.fixture
def ctx(data_dir: Path, inbox: Path) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(Router()))
    use_folder(context, inbox)
    yield context
    context.close()


async def test_the_watched_folder_refuses_it_with_the_reason(
    ctx: AppContext, inbox: Path, unlaid: None
) -> None:
    (inbox / "rechnung.eml").write_bytes(MAIL)
    async with watching(ctx):
        await eventually(lambda: logged(ctx, "folder.refused"))
    assert logged(ctx, "folder.refused") == [
        f"Couldn't add “rechnung.eml” from your watched folder: {UNLAID_TEXT}"
    ]
    assert ctx.store.list_documents() == []


def test_ordnung_add_refuses_it_without_a_traceback(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch, unlaid: None
) -> None:
    monkeypatch.setattr(cli, "open_context", lambda folder: build_context(folder, backend_obj=fake_backend()))
    mail = tmp_path / "rechnung.eml"
    mail.write_bytes(MAIL)
    result = invoke("add", str(mail), "--data-dir", str(data_dir))
    assert result.exit_code == 1
    assert UNLAID_TEXT in _flat(result.output) and "Traceback" not in result.output
