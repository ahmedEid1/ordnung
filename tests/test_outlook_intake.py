"""Outlook ``.msg`` files at every way in: upload, the phone, the watched folder, ``ordnung add`` and proof
of a sent letter. Each becomes an e-mail (``.eml``) whose attachments are letters of their own, adding it
again finds it, a damaged one is refused with the Outlook reason, and one whose first kilobyte holds an
attached PDF is no longer called a broken PDF (intake's sniffing sees ``%PDF-`` there: the conversion runs
before it, and intake itself is unchanged)."""

from __future__ import annotations

import email
import email.policy
import json
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

import pytest

from fixtures_llm import TODAY, Router, fake_backend
from helpers_docs import Line, make_pdf
from helpers_msg import Attachment, bill, build_msg
from ordnung import cli, clock
from ordnung.app_context import AppContext, build_context
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.ingest import held, watcher
from ordnung.ingest.attachments import email_attachments, email_source
from ordnung.ingest.intake import normalise_upload, sniff_mime
from ordnung.ingest.outlook import DAMAGED, msg_to_eml
from ordnung.ingest.text import email_heading, text_document
from ordnung.llm.fake import FakeBackend
from phone_support import pair, phone_app, phone_client
from test_api_proof import _add, _sent
from test_api_support import api_for
from test_cli import invoke
from test_folder_watcher import eventually, logged, picked, use_folder, watching

BILL = build_msg(bill())
BROKEN_PDF = "This PDF could not be opened"
HEADING = "Ihre Rechnung September 2026 · Stadtwerke Musterstadt"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def test_the_bill_holds_a_pdf_in_its_first_kilobyte() -> None:
    """The trap every test here walks into: intake alone takes this Outlook file for a PDF."""
    assert b"%PDF-" in BILL[:1024]
    assert sniff_mime(BILL, "Rechnung.msg") == "application/pdf"


def test_converted_text_has_header_lines_and_attachment_list() -> None:
    eml = msg_to_eml(BILL)
    body, mime, name = normalise_upload(eml, "Rechnung.eml")
    assert (body, mime, name) == (eml, "message/rfc822", "Rechnung.eml")
    lines = text_document(eml, mime).text.splitlines()
    assert [line.split(":", 1)[0] for line in lines[:4]] == ["From", "To", "Date", "Subject"]
    assert lines[0] == "From: Stadtwerke Musterstadt <rechnung@stadtwerke-musterstadt.example>"
    assert lines[4] == "Attachments: Rechnung_2026-09.pdf"
    assert "anbei Ihre Rechnung für September." in lines


def test_held_msg_title_is_subject_and_sender() -> None:
    assert email_heading(msg_to_eml(BILL)) == HEADING


# --------------------------------------------------------------------------------------------------
# Upload and the phone
# --------------------------------------------------------------------------------------------------


async def test_upload_msg_becomes_email_with_its_attachments(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        result = await api.upload(("Rechnung.msg", BILL))
        assert result["errors"] == []
        (document,) = result["documents"]
        assert (document["filename"], document["mime"], document["source"]) == (
            "Rechnung.eml",
            "message/rfc822",
            "upload",
        )
        (attachment,) = api.ctx.store.list_documents(source=email_source(document["id"]))
        assert (attachment.filename, attachment.mime) == ("Rechnung_2026-09.pdf", "application/pdf")
        stored = api.ctx.store.get_document_file(document["id"])
        assert stored is not None and stored.read_bytes() == msg_to_eml(BILL)  # the .eml copy is kept
        assert stored.suffix == ".eml"


async def test_upload_msg_twice_is_a_duplicate(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        (document,) = (await api.upload(("Rechnung.msg", BILL)))["documents"]
        again = await api.upload(("Kopie von Rechnung.msg", BILL))
        assert again["documents"] == [] and again["duplicates"] == [document["id"]]


async def test_msg_holding_a_pdf_is_not_called_a_broken_pdf(data_dir: Path) -> None:
    """Intake alone either refuses such a file as a broken PDF or, when the PDF inside happens to open,
    stores the whole Outlook file as that PDF; converted first, it is the e-mail it is."""
    async with api_for(data_dir) as api:
        response = await api.client.post("/api/documents", files=[("files", ("Rechnung.msg", BILL))])
        assert response.status_code == 201, response.text
        assert BROKEN_PDF not in response.text
        (document,) = response.json()["documents"]
        assert (document["mime"], document["filename"]) == ("message/rfc822", "Rechnung.eml")


async def test_upload_of_a_damaged_msg_says_why(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.post("/api/documents", files=[("files", ("Rechnung.msg", BILL[:3000]))])
        assert response.status_code == 422, response.text
        assert response.json()["errors"] == [{"filename": "Rechnung.msg", "detail": DAMAGED}]


async def test_upload_of_a_msg_full_of_zeros_says_it_is_damaged(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.post("/api/documents", files=[("files", ("kaputt.msg", b"\0" * 8192))])
        assert response.json()["errors"] == [{"filename": "kaputt.msg", "detail": DAMAGED}]


async def test_phone_upload_msg(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        answer = await phone.post("/api/documents", files=[("files", ("Rechnung.msg", BILL))])
        assert answer.status_code == 201, answer.text
        (document,) = answer.json()["documents"]
        assert (document["filename"], document["source"]) == ("Rechnung.eml", "phone")
        assert len(api.ctx.store.list_documents(source=email_source(document["id"]))) == 1


# --------------------------------------------------------------------------------------------------
# The watched folder
# --------------------------------------------------------------------------------------------------


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


def test_watched_folder_lists_msg_files() -> None:
    assert ".msg" in watcher.WATCHED_SUFFIXES
    assert watcher.is_candidate("Rechnung.msg") and watcher.is_candidate("MAIL.MSG")
    assert not watcher.is_candidate("~$Rechnung.msg")


async def test_watched_folder_picks_up_msg_and_holds_it(ctx: AppContext, inbox: Path) -> None:
    (inbox / "Rechnung.msg").write_bytes(BILL)
    async with watching(ctx):
        parent = await eventually(picked(ctx, "Rechnung.eml"))
        child = await eventually(picked(ctx, "Rechnung_2026-09.pdf"))
    assert child.source == email_source(parent.id) and parent.source == "folder"
    assert [doc.status for doc in (parent, child)] == ["held", "held"]
    assert logged(ctx, "folder.refused") == []
    await ctx.worker.run_until_idle()  # read on this computer only: titled from its headers
    titled = ctx.store.get_document(parent.id)
    assert titled is not None and titled.title == HEADING and titled.status == "held"
    backend = ctx.llm.backend
    assert isinstance(backend, FakeBackend) and backend.calls == []  # nothing went to Claude
    assert watcher.was_taken(ctx.store, BILL)  # the file's own bytes are remembered (hand-off sync)


async def test_watched_folder_refused_msg_logged(ctx: AppContext, inbox: Path) -> None:
    (inbox / "kaputt.msg").write_bytes(BILL[:3000])
    async with watching(ctx):
        await eventually(lambda: logged(ctx, "folder.refused"))
    assert logged(ctx, "folder.refused") == [f"Couldn't add “kaputt.msg” from your watched folder: {DAMAGED}"]
    assert ctx.store.list_documents() == []


async def test_watched_folder_refuses_a_msg_full_of_zeros_as_damaged(ctx: AppContext, inbox: Path) -> None:
    (inbox / "kaputt-nullen.msg").write_bytes(b"\0" * 8192)
    async with watching(ctx):
        await eventually(lambda: logged(ctx, "folder.refused"))
    assert logged(ctx, "folder.refused") == [
        f"Couldn't add “kaputt-nullen.msg” from your watched folder: {DAMAGED}"
    ]


async def test_watched_folder_says_a_known_msg_by_its_own_name(ctx: AppContext, inbox: Path) -> None:
    (inbox / "Rechnung.msg").write_bytes(BILL)
    async with watching(ctx):
        await eventually(picked(ctx, "Rechnung.eml"))
        (inbox / "Kopie.msg").write_bytes(BILL)
        await eventually(lambda: logged(ctx, "folder.known"))
    assert logged(ctx, "folder.known") == ["“Kopie.msg” in your watched folder is already in Ordnung"]


async def test_after_the_update_outlook_files_already_in_the_folder_wait(
    ctx: AppContext, inbox: Path
) -> None:
    """0.2.0 left Outlook files in a watched folder alone, and its record of the files there when the folder
    was chosen doesn't list them. After the update they count as files that were there: they wait, with
    their attachments, even with "Read new files with Claude straight away" on. Files of the types watched
    before, and Outlook files that arrive later, are new arrivals as before."""
    (inbox / "Alte Rechnung.msg").write_bytes(BILL)
    (inbox / "neu.pdf").write_bytes(make_pdf([[Line(72, 90, "Kam, während Ordnung zu war")]]))
    use_folder(ctx, inbox, inbox_auto_read=True)
    # what 0.2.0 kept once it had watched this folder: the folder, no files still waiting, no file types
    ctx.store.set_meta(watcher.BASELINE_META_KEY, json.dumps({"folder": str(inbox), "keys": []}))
    async with watching(ctx):
        old = await eventually(picked(ctx, "Alte Rechnung.eml"))
        attached = await eventually(picked(ctx, "Rechnung_2026-09.pdf"))
        arrived = await eventually(picked(ctx, "neu.pdf"))
        (inbox / "Neue Rechnung.msg").write_bytes(build_msg(bill(subject="Neue Rechnung", attachments=[])))
        new = await eventually(picked(ctx, "Neue Rechnung.eml"))
    assert [(doc.status, doc.ai_private) for doc in (old, attached)] == [("held", True)] * 2
    assert (arrived.status, new.status) == ("queued", "queued")
    assert {doc.id for doc in held.waiting(ctx.store)} == {old.id, attached.id}  # nothing for Claude
    stored = json.loads(ctx.store.get_meta(watcher.BASELINE_META_KEY) or "{}")
    assert stored["suffixes"] == sorted(watcher.WATCHED_SUFFIXES)
    (inbox / "Während zu.msg").write_bytes(build_msg(bill(subject="Während zu", attachments=[])))
    async with watching(ctx):  # once updated, an Outlook file that came while Ordnung was closed arrived
        later = await eventually(picked(ctx, "Während zu.eml"))
    assert later.status == "queued"


# --------------------------------------------------------------------------------------------------
# ordnung add, and proof of a sent letter
# --------------------------------------------------------------------------------------------------


def test_cli_add_msg_in_process(tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "open_context", lambda folder: build_context(folder, backend_obj=fake_backend()))
    mail = tmp_path / "Rechnung.msg"
    mail.write_bytes(BILL)
    result = invoke("add", str(mail), "--private", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert BROKEN_PDF not in result.output
    store = Store.open(Paths(data_dir))
    try:
        (document,) = [doc for doc in store.list_documents() if doc.source == "cli"]
        assert (document.filename, document.mime) == ("Rechnung.eml", "message/rfc822")
        assert [doc.filename for doc in store.list_documents(source=email_source(document.id))] == [
            "Rechnung_2026-09.pdf"
        ]
    finally:
        store.close()


def test_cli_add_damaged_msg_says_why(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "open_context", lambda folder: build_context(folder, backend_obj=fake_backend()))
    mail = tmp_path / "kaputt.msg"
    mail.write_bytes(BILL[:3000])
    result = invoke("add", str(mail), "--data-dir", str(data_dir))
    assert result.exit_code == 1
    assert "This Outlook file can't be opened" in result.output and "Traceback" not in result.output


async def test_proof_msg_kept_as_one_file(data_dir: Path) -> None:
    """A sent e-mail saved from Outlook is kept as proof like an .eml: one private file, its attachments no
    letters."""
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        before = {doc.id for doc in api.ctx.store.list_documents(include_deleted=True)}
        overview = await _add(api, draft_id, "gesendet.msg", BILL, kind="sent_email")
        (entry,) = overview["proofs"]
        assert (entry["document"]["filename"], entry["document"]["mime"]) == (
            "gesendet.eml",
            "message/rfc822",
        )
        added = {doc.id for doc in api.ctx.store.list_documents(include_deleted=True)} - before
        assert added == {entry["document"]["id"]}
        stored = api.ctx.store.get_document_file(entry["document"]["id"])
        assert stored is not None
        message = email.message_from_bytes(stored.read_bytes(), policy=email.policy.default)
        assert [part.get_filename() for part in message.iter_attachments()] == ["Rechnung_2026-09.pdf"]


async def test_proof_of_a_damaged_msg_says_why(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        response = await api.client.post(
            f"/api/drafts/{draft_id}/proofs",
            files={"file": ("gesendet.msg", BILL[:3000])},
            data={"kind": "sent_email"},
        )
        assert response.status_code == 422 and response.json()["detail"] == DAMAGED


# --------------------------------------------------------------------------------------------------
# An Outlook file inside an e-mail
# --------------------------------------------------------------------------------------------------


def test_an_outlook_file_attached_to_an_email_is_listed_never_read() -> None:
    """An Outlook (or older Office) file attached to an e-mail is listed and never opened, like a forwarded
    e-mail, even when its first kilobyte holds a PDF (the attachment policy decides by the bytes)."""
    outer = EmailMessage()
    outer["From"] = "Sam Rivera <sam@example.org>"
    outer["Subject"] = "Weitergeleitet: Rechnung"
    outer.set_content("Siehe Anhang.\n")
    outer.add_attachment(BILL, maintype="application", subtype="vnd.ms-outlook", filename="Rechnung.msg")
    decisions = [
        (found.filename, found.decision) for found in email_attachments(outer.as_bytes()).attachments
    ]
    assert decisions == [("Rechnung.msg", "not_read")]


def test_an_outlook_file_attached_by_value_inside_a_msg_is_listed_never_read() -> None:
    eml = msg_to_eml(
        build_msg(bill(attachments=[Attachment("Weitergeleitet.msg", BILL, "application/vnd.ms-outlook")]))
    )
    decisions = [(found.filename, found.decision) for found in email_attachments(eml).attachments]
    assert decisions == [("Weitergeleitet.msg", "not_read")]
